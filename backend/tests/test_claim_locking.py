"""Every claim re-check must lock its row, and all writers must agree on the order.

Two separate defects live here.

*Atomicity*: check-then-act on an unlocked read is not atomic, so two workers
holding the same claim both pass the check and both write. A success and a
timeout interleaved that way leave `sent_message_id` set *and* `error_message`
set — a tag that was delivered gets recorded as failed and queued again.

*Ordering*: once those reads do take locks, disagreeing on the order deadlocks.
The trap in the debt path is that the foreign key from `bot_delivery_logs` to
`customers` makes writing a delivery log an implicit lock on the customer row, so
a function that merely logs still has to take the customer lock in its turn.

Asserting on the *presence* of FOR UPDATE is not enough — a deadlocking version
passes that. These tests record the statements the production code actually
issues, in order, and check which tables get locked and when.

What the static scan at the bottom does and does not cover, so nobody reads more
assurance into a green run than is there:

*Covered.* Every `with_for_update()` in ``app/`` is classified. A statement is
flagged as multi-table for `.join`, `.outerjoin`, `.join_from`,
`select_from(join(...))`, `select_from(X.__table__.join(...))`, two or more
distinct entities in the `select(...)`, or a mapped model named in a
`where`/`filter` that the select does not name. Any of those without `of=`
fails, and an `of=` naming an entity the statement does not select fails. A chain
the walker cannot follow back to `select(...)` fails unless it carries the waiver
comment, and the waiver is refused inside any function that builds a SQL join.

The two checks are calibrated differently on purpose. Classifying a statement is
precise, so a single-table lock is not nagged about. Judging a *waiver* is
conservative: any join-shaped call whose receiver is not a string literal voids
it, even one reached through a variable (`statement = statement.join(B)`), which
no amount of local inspection can prove is SQL. Wrongly rejecting a waiver costs
an inlined statement; wrongly accepting one hides a deadlock.

Deliberately *not* flagged, because they are single-table: several columns of one
table (`select(A.id, A.name)`), and a Python `",".join(...)` sitting in the same
function as a waiver.

*Not covered.* Two single-table writers taking their locks in opposite orders —
the original debt deadlock — is invisible to this scan; only the recorder tests
above, and reading the code, catch that. Nor does it flag `order_by(B.name)` or
`having(...)` pulling in a table, follow a statement built by a helper in another
module, or resolve entities passed through a variable
(`select(A, some_model_var)` reads as single-table). The waiver remains a human
claim about the cases the walker gave up on.
"""

import ast
import pathlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.models import (
    Customer,
    DebtReminderAutomation,
    DebtReminderRun,
    MentionAutomation,
    MentionContextMessage,
    MentionFollowup,
    MentionTarget,
    ZaloAccount,
    ZaloGroup,
)
from app.models.entities import DebtReminderStatus, DeliveryType, MentionFollowupStatus
from app.schemas.api import IncomingGroupMessage, IncomingMention
from app.services import (
    debt_reminder_scheduler,
    mention_automation_service,
    mention_scheduler,
)

_LOCKED_TABLE = re.compile(r"\bFROM\s+([a-z_]+)", re.IGNORECASE)


class _LockRecorder:
    """A real session that also records every statement it is handed."""

    def __init__(self, inner, log: list) -> None:
        self._inner = inner
        self._log = log

    async def scalar(self, statement, *args, **kwargs):
        self._log.append(statement)
        return await self._inner.scalar(statement, *args, **kwargs)

    async def execute(self, statement, *args, **kwargs):
        self._log.append(statement)
        return await self._inner.execute(statement, *args, **kwargs)

    async def scalars(self, statement, *args, **kwargs):
        self._log.append(statement)
        return await self._inner.scalars(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        await self._inner.close()
        return False


def _locked_tables(statements: list) -> list[str]:
    """Tables the recorded statements take a row lock on, in the order taken."""
    tables: list[str] = []
    for statement in statements:
        sql = str(statement.compile(dialect=postgresql.dialect()))
        if "FOR UPDATE" not in sql:
            continue
        match = _LOCKED_TABLE.search(sql)
        if match:
            tables.append(match.group(1))
    return tables


def _assert_follows_lock_order(tables: list[str]) -> None:
    """The locked tables must be a subsequence of the agreed order.

    Skipping a lock is fine; taking two out of order is what deadlocks.
    """
    order = list(debt_reminder_scheduler._LOCK_ORDER)
    position = -1
    for table in tables:
        assert table in order, f"bang {table} chua co trong _LOCK_ORDER"
        index = order.index(table)
        assert index > position, (
            f"khoa sai thu tu: {tables} khong phai day con cua {order}"
        )
        position = index


async def _debt_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="lock-group",
            name="Nhóm lock",
            member_count=2,
            is_available=True,
            last_synced_at=now,
        )
        db.add(group)
        await db.flush()
        customer = Customer(
            zalo_group_id=group.id,
            has_debt=True,
            debt_file_url="https://docs.google.com/spreadsheets/d/lock/edit",
        )
        db.add(customer)
        await db.flush()
        automation = DebtReminderAutomation(customer_id=customer.id, next_run_at=None)
        db.add(automation)
        await db.flush()
        run = DebtReminderRun(
            automation_id=automation.id,
            scheduled_for=now,
            retry_at=now,
            status=DebtReminderStatus.PROCESSING,
            claimed_at=now,
        )
        db.add(run)
        await db.commit()
        return engine, sessions, customer.id, run.id, run.claimed_at


async def test_debt_fail_run_locks_customer_before_run(monkeypatch) -> None:
    """Taking the run first put this function opposite _send_step_if_current.

    That is a genuine deadlock: the send path holds the customer and waits for the
    run, while this path holds the run and waits for the customer via the
    delivery-log foreign key.
    """
    engine, sessions, customer_id, run_id, claimed_at = await _debt_database()
    log: list = []

    async def noop_report(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(debt_reminder_scheduler, "report_async", noop_report)
    monkeypatch.setattr(
        debt_reminder_scheduler,
        "SessionLocal",
        lambda: _LockRecorder(sessions(), log),
    )

    run = DebtReminderRun(id=run_id, claimed_at=claimed_at)
    await debt_reminder_scheduler._fail_run(run, customer_id, "CODE", "loi thu")

    tables = _locked_tables(log)
    assert tables == ["customers", "debt_reminder_runs"], tables
    _assert_follows_lock_order(tables)

    async with sessions() as db:
        stored = await db.get(DebtReminderRun, run_id)
        assert stored is not None
        assert stored.error_code == "CODE"
    await engine.dispose()


async def test_debt_send_step_locks_customer_then_automation_then_run(
    monkeypatch,
) -> None:
    engine, sessions, customer_id, run_id, claimed_at = await _debt_database()
    log: list = []

    monkeypatch.setattr(
        debt_reminder_scheduler,
        "SessionLocal",
        lambda: _LockRecorder(sessions(), log),
    )

    async def fake_send(_key: str) -> dict[str, str]:
        return {"message_id": "sent-1"}

    sent, message_id = await debt_reminder_scheduler._send_step_if_current(
        run_id,
        claimed_at,
        customer_id,
        DeliveryType.DEBT_REMINDER_IMAGE,
        "image_message_id",
        fake_send,
    )
    assert sent is True
    assert message_id == "sent-1"

    tables = _locked_tables(log)
    assert tables == [
        "customers",
        "debt_reminder_automations",
        "debt_reminder_runs",
    ], tables
    _assert_follows_lock_order(tables)
    await engine.dispose()


async def test_every_debt_writer_agrees_on_the_lock_order(monkeypatch) -> None:
    """_finish_without_sending holds only a suffix, which is allowed."""
    engine, sessions, _customer_id, run_id, claimed_at = await _debt_database()
    log: list = []
    monkeypatch.setattr(
        debt_reminder_scheduler,
        "SessionLocal",
        lambda: _LockRecorder(sessions(), log),
    )

    await debt_reminder_scheduler._finish_without_sending(
        run_id, claimed_at, DebtReminderStatus.SKIPPED, "đã thanh toán"
    )

    tables = _locked_tables(log)
    assert tables == ["debt_reminder_runs"], tables
    _assert_follows_lock_order(tables)
    await engine.dispose()


async def test_mention_reload_claim_locks_the_followup_row(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="lock-mention",
            name="Nhóm lock",
            member_count=2,
            is_available=True,
            last_synced_at=now,
        )
        db.add(group)
        await db.flush()
        db.add(Customer(id=group.id, zalo_group_id=group.id))
        automation = MentionAutomation(
            zalo_group_id=group.id,
            enabled=True,
            mention_tag_enabled=True,
            delay_minutes=1,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        followup = MentionFollowup(
            automation_id=automation.id,
            source_message_id="lock-source",
            target_user_ids=["target-user"],
            target_display_names=["Người cần trả lời"],
            due_at=now,
            status=MentionFollowupStatus.PROCESSING,
            claimed_at=now,
        )
        db.add(followup)
        await db.commit()
        followup_id = followup.id
        followup_claimed_at = followup.claimed_at

    job = mention_scheduler._FollowupJob(
        followup_id=followup_id,
        claimed_at=followup_claimed_at,
        zalo_group_id="lock-mention",
        customer_id=None,
        customer_name="Nhóm lock",
        delay_minutes=1,
        active_windows=[{"start": "00:00", "end": "23:59"}],
        targets=[{"user_id": "target-user", "display_name": "Người cần trả lời"}],
        idempotency_key="mention:lock:0",
    )

    log: list = []
    async with sessions() as inner:
        recorder = _LockRecorder(inner, log)
        found = await mention_scheduler._reload_claim(recorder, job)
        assert found is not None

    tables = _locked_tables(log)
    assert tables == ["mention_followups"], (
        f"doc claim khong khoa row: {tables}. Hai worker cung claim se ghi de len nhau"
    )
    await engine.dispose()


def test_lock_order_names_real_tables() -> None:
    # Guards the ordering assertions above against a typo or a table rename.
    names = {
        Customer.__tablename__,
        DebtReminderAutomation.__tablename__,
        DebtReminderRun.__tablename__,
    }
    assert set(debt_reminder_scheduler._LOCK_ORDER) == names
    assert debt_reminder_scheduler._LOCK_ORDER[0] == Customer.__tablename__, (
        "customers phai la lock dau tien: FK cua bot_delivery_logs se can no"
    )


def test_mention_followup_model_still_has_the_fields_these_writers_touch() -> None:
    for field in ("status", "claimed_at", "send_attempt_count", "send_count"):
        assert field in MentionFollowup.__table__.columns


def test_delivery_log_still_references_customers() -> None:
    """The premise of the whole ordering rule.

    If this FK ever goes away, writing a delivery log stops locking the customer
    row and _fail_run no longer needs to take that lock first.
    """
    from app.models import BotDeliveryLog

    targets = {
        foreign_key.column.table.name
        for foreign_key in BotDeliveryLog.__table__.foreign_keys
    }
    assert Customer.__tablename__ in targets


# ---------------------------------------------------------------------------
# Static guard: `FOR UPDATE` over more than one table must scope itself.
#
# The recorder tests above only see the functions they call. The group-sync
# deadlock lived in a function no test touched, so a green suite proved nothing
# about it. This walks the source instead.
# ---------------------------------------------------------------------------

#: Chain methods that make a statement span more than one table.
_MULTI_TABLE_METHODS = {"join", "outerjoin", "join_from", "select_from"}

#: Certifies a `with_for_update()` this walker cannot follow statically —
#: because the statement was built across several assignments — as reviewed and
#: single-table. Without it, an unfollowable lock read fails the guard.
_SINGLE_TABLE_WAIVER = "lock-scope: single-table"


@dataclass(frozen=True)
class _LockingRead:
    path: str
    line: int
    #: Statement touches more than one table, so a bare FOR UPDATE over-locks.
    multi_table: bool
    #: False when the chain could not be followed back to a select() call.
    resolved: bool
    #: Entities passed positionally to select(), when resolvable.
    selected: tuple[str, ...]
    of_targets: tuple[str, ...]
    waived: bool


def _dotted_segments(node: ast.expr) -> list[str]:
    """The dotted path of a reference, root first: `models.A.id` -> [models, A, id]."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [*_dotted_segments(node.value), node.attr]
    if isinstance(node, ast.Call):
        return _dotted_segments(node.func)
    return []


def _entity_name(node: ast.expr) -> str | None:
    """The model a reference points at, ignoring module prefix and column suffix.

    Models are CamelCase here, so the last CamelCase segment of the dotted path
    is the entity: `models.A` -> A, `A.id` -> A, `ZaloGroup.id` -> ZaloGroup.
    Naively returning the root Name made `models.A` and `models.B` both read as
    "models", which let a wrong `of=` satisfy the subset check.
    """
    for segment in reversed(_dotted_segments(node)):
        if segment[:1].isupper() and not segment.startswith("_"):
            return segment
    return None


def _mapped_class_names() -> frozenset[str]:
    """Every mapped model, so the scan can tell a table from an enum.

    Filtering on "looks CamelCase" flagged `where(status == DebtReminderStatus.PENDING)`
    as pulling in a second table. Asking the mapper registry is exact.
    """
    return frozenset(mapper.class_.__name__ for mapper in Base.registry.mappers)


def _referenced_entities(
    nodes: Iterable[ast.expr], entity_names: frozenset[str]
) -> set[str]:
    found: set[str] = set()
    for node in nodes:
        for inner in ast.walk(node):
            if isinstance(inner, ast.Attribute):
                name = _entity_name(inner)
                if name in entity_names:
                    found.add(name)
    return found


def _of_targets(node: ast.Call) -> tuple[str, ...]:
    for keyword in node.keywords:
        if keyword.arg != "of":
            continue
        value = keyword.value
        items = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
        return tuple(name for name in (_entity_name(item) for item in items) if name)
    return ()


def _is_join_expression(node: ast.AST, entity_names: frozenset[str]) -> bool:
    """Any expression that joins tables: `join(A, B)` or `A.__table__.join(B)`.

    The two forms need different tests. Matching the dotted path's last segment
    for both accepted `",".join(values)` as well, because the path of a string
    literal receiver is empty and only "join" was left to look at.
    """
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name):
        return node.func.id in {"join", "outerjoin"}
    return _is_sql_join_call(node, entity_names)


def _is_multi_table_call(node: ast.Call, entity_names: frozenset[str]) -> bool:
    """`select_from` only widens the statement when it is given a join."""
    if _is_sql_join_call(node, entity_names):
        return True
    attribute = node.func.attr if isinstance(node.func, ast.Attribute) else ""
    if attribute != "select_from":
        return False
    return (
        any(_is_join_expression(argument, entity_names) for argument in node.args)
        or len(node.args) > 1
    )


def _is_sql_join_call(node: ast.AST, entity_names: frozenset[str]) -> bool:
    """A `.join()` that joins tables, as opposed to `",".join(values)`.

    Matching on the method name alone counted every string join, which would
    reject a perfectly good waiver in any function that also formats a list.
    """
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"join", "outerjoin", "join_from"}
    ):
        return False
    receiver = node.func.value
    if isinstance(receiver, ast.Constant):
        return False
    segments = _dotted_segments(receiver)
    if segments[:1] == ["select"]:
        return True
    return _entity_name(receiver) in entity_names or "__table__" in segments


def _might_be_a_join(node: ast.AST) -> bool:
    """Deliberately conservative: anything join-shaped that is not a string join.

    Used *only* to decide whether a waiver is trustworthy, where the two kinds of
    mistake are not symmetric. Wrongly rejecting a waiver costs somebody the
    trouble of inlining a statement; wrongly accepting one hides a deadlock.

    So this does not try to prove the receiver is a SQLAlchemy object — the
    precise `_is_sql_join_call` cannot, once the statement has been through a
    variable. `statement = statement.join(B)` leaves nothing but a bare name to
    look at, and that form slipped past the precise check entirely.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in {"join", "outerjoin"}
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr not in {"join", "outerjoin", "join_from"}:
        return False
    # `",".join(parts)` and `b"".join(...)` are the only join-shaped calls in this
    # codebase that are not SQL, and a literal receiver identifies them exactly.
    return not isinstance(node.func.value, ast.Constant)


def _scopes_that_build_joins(tree: ast.AST) -> list[tuple[int, int]]:
    """Line ranges of functions that might build a SQL join anywhere inside them."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if any(_might_be_a_join(inner) for inner in ast.walk(node)):
            ranges.append((node.lineno, node.end_lineno or node.lineno))
    return ranges


def _in_joining_scope(line: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= line <= end for start, end in ranges)


def scan_locking_reads(
    source: str,
    path: str = "<memory>",
    entity_names: frozenset[str] | None = None,
) -> list[_LockingRead]:
    """Every `with_for_update()` in `source`, with what can be proven about it.

    `entity_names` is the set of mapped models; the synthetic fixture below passes
    its own so it can use throwaway model names.
    """
    if entity_names is None:
        entity_names = _mapped_class_names()
    lines = source.splitlines()
    tree = ast.parse(source)
    joining_scopes = _scopes_that_build_joins(tree)
    found: list[_LockingRead] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "with_for_update"
        ):
            continue
        multi_table = False
        resolved = False
        selected: tuple[str, ...] = ()
        # A model named anywhere in a WHERE/filter drags its table into the FROM
        # list, so `select(A).where(A.id == B.a_id)` locks B as well without ever
        # saying "join". Collected here and compared against the select below.
        filtered_entities: set[str] = set()
        current: ast.expr | None = node.func.value
        while current is not None:
            if isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
                multi_table = multi_table or _is_multi_table_call(
                    current, entity_names
                )
                if current.func.attr in {"where", "filter"}:
                    filtered_entities |= _referenced_entities(
                        current.args, entity_names
                    )
                current = current.func.value
            elif isinstance(current, ast.Call) and _dotted_segments(current.func) == [
                "select"
            ]:
                resolved = True
                selected = tuple(
                    name for name in (_entity_name(a) for a in current.args) if name
                )
                # Distinct entities, not argument count: `select(A.id, A.name)`
                # is two columns of one table, not two tables.
                multi_table = multi_table or len(set(selected)) > 1
                break
            else:
                break
        if resolved and filtered_entities - set(selected):
            multi_table = True
        window = "\n".join(lines[max(0, node.lineno - 4) : node.lineno + 1])
        found.append(
            _LockingRead(
                path=path,
                line=node.lineno,
                multi_table=multi_table,
                resolved=resolved,
                selected=selected,
                of_targets=_of_targets(node),
                # A waiver is a human claim, so refuse it where it could be
                # wrong: if the enclosing function builds a join at all, the
                # split statement is not demonstrably single-table.
                waived=(
                    _SINGLE_TABLE_WAIVER in window
                    and not _in_joining_scope(node.lineno, joining_scopes)
                ),
            )
        )
    return found


def _scan_app() -> list[_LockingRead]:
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    reads: list[_LockingRead] = []
    for path in sorted(root.rglob("*.py")):
        reads.extend(
            scan_locking_reads(
                path.read_text(encoding="utf-8"), str(path.relative_to(root.parent))
            )
        )
    return reads


def test_every_multi_table_locking_read_scopes_itself_with_of() -> None:
    """`FOR UPDATE` over a join locks a row in *every* joined table.

    Two problems at once: it holds locks the code never meant to take, and the
    order it takes them in is up to the query plan — so it can grab the child
    before the parent and deadlock against a writer going the other way.
    """
    offenders = [
        f"{read.path}:{read.line}"
        for read in _scan_app()
        if read.multi_table and not read.of_targets
    ]
    assert not offenders, (
        f"with_for_update() tren nhieu bang ma thieu of=, co the deadlock: {offenders}"
    )


def test_of_targets_an_entity_the_statement_actually_selects() -> None:
    """`of=` pointing at the wrong table silently reintroduces the bug.

    `select(MentionAutomation).join(ZaloGroup).with_for_update(of=ZaloGroup)`
    passes a mere presence check while locking the wrong row entirely.
    """
    wrong = [
        f"{read.path}:{read.line} (of={read.of_targets}, selects={read.selected})"
        for read in _scan_app()
        if read.of_targets
        and read.resolved
        and not set(read.of_targets) <= set(read.selected)
    ]
    assert not wrong, f"of= khong tro vao entity ma statement select: {wrong}"


def test_locking_reads_the_walker_cannot_follow_are_explicitly_waived() -> None:
    """Nothing gets to pass just because the walker could not read it.

    A statement assembled across assignments is invisible to this scan, so it
    must carry the waiver comment certifying somebody checked it is single-table.
    """
    unverified = [
        f"{read.path}:{read.line}"
        for read in _scan_app()
        if not read.resolved and not read.waived
    ]
    assert not unverified, (
        "khong lan duoc chain ve select(); hay inline statement hoac them comment"
        f" '# {_SINGLE_TABLE_WAIVER}': {unverified}"
    )


_SCANNER_FIXTURE = '''
from sqlalchemy import join, select
from app.models import A, B
from app import models

bad_join = select(A).join(B).with_for_update()
good_join = select(A).join(B).with_for_update(of=A)
bad_outerjoin = select(A).outerjoin(B).with_for_update()
bad_select_from = select(A).select_from(join(A, B)).with_for_update()
bad_table_join = select(A).select_from(A.__table__.join(B)).with_for_update()
bad_two_entities = select(A, B).with_for_update()
bad_where_pulls_b = select(A).where(A.id == B.a_id).with_for_update()
plain_single = select(A).where(A.id == 1).with_for_update()
column_single = select(A.id).where(A.id == 1).with_for_update()
two_columns_one_table = select(A.id, A.name).with_for_update()
skip_locked_join = select(A).join(B).with_for_update(of=A, skip_locked=True)
namespaced_wrong_of = select(models.A).join(models.B).with_for_update(of=models.B)
namespaced_right_of = select(models.A).join(models.B).with_for_update(of=models.A)
list_of = select(A).join(B).with_for_update(of=[A])


def indirect_single():
    statement = select(A)
    # lock-scope: single-table
    return statement.with_for_update()


def indirect_unwaived():
    statement = select(A)
    return statement.with_for_update()


def indirect_waiver_in_joining_scope():
    statement = select(A).join(B)
    # lock-scope: single-table
    return statement.with_for_update()


def indirect_with_only_a_string_join(values):
    label = ",".join(values)
    statement = select(A)
    # lock-scope: single-table
    return label, statement.with_for_update()


def indirect_join_by_reassignment():
    statement = select(A)
    statement = statement.join(B)
    # lock-scope: single-table
    return statement.with_for_update()


def indirect_outerjoin_by_reassignment():
    statement = select(A)
    statement = statement.outerjoin(B)
    # lock-scope: single-table
    return statement.with_for_update()


def indirect_join_from_by_reassignment():
    statement = select(A)
    statement = statement.join_from(A, B)
    # lock-scope: single-table
    return statement.with_for_update()
'''

_FIXTURE_ENTITIES = frozenset({"A", "B"})


def _fixture_line(marker: str) -> int:
    for index, text in enumerate(_SCANNER_FIXTURE.splitlines()):
        if text.strip().startswith(marker):
            return index + 1
    raise AssertionError(f"khong tim thay dong cho {marker}")


def test_the_scanner_classifies_a_synthetic_fixture_correctly() -> None:
    """Validates the walker itself, instead of asserting on production topology.

    Tying the anti-vacuous check to "app/ has at least N joins" made it fail the
    moment a join was legitimately refactored away.
    """
    reads = scan_locking_reads(_SCANNER_FIXTURE, entity_names=_FIXTURE_ENTITIES)
    by_line = {read.line: read for read in reads}
    source_lines = _SCANNER_FIXTURE.splitlines()

    def read_for(marker: str) -> _LockingRead:
        line = next(
            index + 1
            for index, text in enumerate(source_lines)
            if text.strip().startswith(marker)
        )
        assert line in by_line, f"khong tim thay with_for_update cho {marker}"
        return by_line[line]

    # Every way SQLAlchemy can widen a statement, not just `.join()`.
    for marker in (
        "bad_join",
        "bad_outerjoin",
        "bad_select_from",
        "bad_table_join",
        "bad_two_entities",
        "bad_where_pulls_b",
    ):
        read = read_for(marker)
        assert read.multi_table, f"{marker} phai bi coi la nhieu bang"
        assert not read.of_targets, marker

    for marker in ("good_join", "skip_locked_join", "list_of"):
        read = read_for(marker)
        assert read.multi_table, marker
        assert read.of_targets == ("A",), f"{marker}: {read.of_targets}"
        assert set(read.of_targets) <= set(read.selected), marker

    # A module prefix must not collapse two different models into one name.
    wrong = read_for("namespaced_wrong_of")
    assert wrong.selected == ("A",), wrong.selected
    assert wrong.of_targets == ("B",), wrong.of_targets
    assert not set(wrong.of_targets) <= set(wrong.selected)
    right = read_for("namespaced_right_of")
    assert set(right.of_targets) <= set(right.selected)

    # Single-table locks are not flagged, including a column-only select and
    # several columns of the same table — argument count is not table count.
    for marker in ("plain_single", "column_single", "two_columns_one_table"):
        read = read_for(marker)
        assert not read.multi_table, marker
        assert read.resolved, marker

    # Chains built across assignments are unresolved, so they lean on the waiver.
    # It counts only where the enclosing function builds no SQL join.
    unresolved = [read for read in reads if not read.resolved]
    assert len(unresolved) == 7, unresolved
    waived = sorted(read.line for read in unresolved if read.waived)

    # A Python string join is not a SQL join and must not cost a valid waiver.
    honoured = [
        _fixture_line("return statement.with_for_update()"),
        _fixture_line("return label, statement.with_for_update()"),
    ]
    assert waived == sorted(honoured), (
        "waiver chi duoc chap nhan trong ham khong dung SQL join:"
        f" waived={waived} expected={sorted(honoured)}"
    )

    # A join reached through a variable leaves only a bare name to inspect, so
    # the scope check has to treat every non-string join as suspect. All three
    # spellings used to slip through with waived=True.
    for scope in (
        "def indirect_join_by_reassignment",
        "def indirect_outerjoin_by_reassignment",
        "def indirect_join_from_by_reassignment",
    ):
        start = _fixture_line(scope)
        inside = [read for read in unresolved if read.line > start][:1]
        assert inside and not inside[0].waived, (
            f"{scope}: JOIN qua bien phai lam waiver bi tu choi"
        )


async def _mention_group_database(*, available: bool = True):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with sessions() as db:
        account = ZaloAccount()
        db.add(account)
        await db.flush()
        group = ZaloGroup(
            zalo_account_id=account.id,
            zalo_group_id="order-group",
            name="Nhóm thứ tự",
            member_count=2,
            is_available=available,
            last_synced_at=now,
        )
        db.add(group)
        await db.flush()
        db.add(Customer(id=group.id, zalo_group_id=group.id))
        automation = MentionAutomation(
            zalo_group_id=group.id,
            enabled=True,
            mention_tag_enabled=True,
            delay_minutes=1,
            active_windows=[{"start": "00:00", "end": "23:59"}],
        )
        db.add(automation)
        await db.flush()
        db.add(
            MentionTarget(
                automation_id=automation.id,
                zalo_user_id="target-user",
                display_name="Người cần trả lời",
            )
        )
        await db.commit()
        return engine, sessions


async def test_mention_event_locks_the_group_before_its_automation() -> None:
    """Two statements, group first — not one join.

    A joined `FOR UPDATE` deadlocks against sync_groups, and narrowing it to
    `of=MentionAutomation` instead drops the group out of the lock: Postgres only
    re-checks a predicate for rows it locks, so a sync that turned the group
    unavailable mid-wait would still hand this an automation.
    """
    engine, sessions = await _mention_group_database()
    log: list = []
    async with sessions() as inner:
        recorder = _LockRecorder(inner, log)
        automation = await mention_automation_service._lock_enabled_automation(
            recorder, "order-group"
        )
        assert automation is not None

    tables = _locked_tables(log)
    assert tables == ["zalo_groups", "mention_automations"], (
        f"phai khoa group truoc automation, cung thu tu voi sync_groups: {tables}"
    )
    await engine.dispose()


async def test_the_message_path_still_preloads_its_targets() -> None:
    """load_targets keeps the message flow from losing who to tag.

    The reaction path does not need them, so it does not pay for the extra query.
    """
    engine, sessions = await _mention_group_database()
    async with sessions() as db:
        automation = await mention_automation_service._lock_enabled_automation(
            db, "order-group", load_targets=True
        )
        assert automation is not None
        # Already loaded: touching this outside a greenlet would otherwise raise.
        assert "targets" not in inspect(automation).unloaded
        assert [target.zalo_user_id for target in automation.targets] == ["target-user"]

        reaction_view = await mention_automation_service._lock_enabled_automation(
            db, "order-group"
        )
        assert reaction_view is not None
    await engine.dispose()


async def test_an_unavailable_group_yields_no_automation_to_act_on() -> None:
    engine, sessions = await _mention_group_database(available=False)
    async with sessions() as db:
        assert (
            await mention_automation_service._lock_enabled_automation(db, "order-group")
        ) is None
    await engine.dispose()


async def test_an_unavailable_group_creates_no_mention_work() -> None:
    """The invariant the locking exists to protect, end to end."""
    engine, sessions = await _mention_group_database(available=False)
    async with sessions() as db:
        response = await mention_automation_service.schedule_from_incoming_event(
            db,
            IncomingGroupMessage(
                group_id="order-group",
                message_id="m-unavailable",
                sender_id="customer-user",
                sender_display_name="Khách",
                content="@Người cần trả lời cho em hỏi",
                sent_at=datetime.now(UTC),
                mentions=[
                    IncomingMention(
                        user_id="target-user",
                        position=0,
                        length=18,
                        text="@Người cần trả lời",
                    )
                ],
            ),
        )
    assert response.scheduled is False
    assert response.followup_id is None

    async with sessions() as db:
        assert list((await db.scalars(select(MentionFollowup))).all()) == []
        assert list((await db.scalars(select(MentionContextMessage))).all()) == []
    await engine.dispose()
