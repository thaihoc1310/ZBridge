import assert from "node:assert/strict";
import test from "node:test";
import { Reaction, Reactions, type TReaction } from "zca-js";
import { incomingReactionEvent } from "../src/zalo/zca-client.js";

function reaction(
  icon: Reactions,
  options: { uidFrom?: string; isGroup?: boolean } = {},
): Reaction {
  const data: TReaction = {
    actionId: "reaction-action",
    msgId: "reaction-message",
    cliMsgId: "1782286279460",
    msgType: "chat.reaction",
    uidFrom: options.uidFrom ?? "target-user_0",
    idTo: "group-reaction",
    dName: "Người cần phản hồi",
    content: {
      // Mobile Zalo may send gMsgID=0. It must not matter because acknowledgement
      // is intentionally based only on group, reactor and reaction kind.
      rMsg: [{ gMsgID: "0", cMsgID: "1782286269667", msgType: 1 }],
      rIcon: icon,
      rType: icon === Reactions.HEART ? 5 : 0,
      source: 0,
    },
    ts: "1782286279518",
    ttl: 0,
  };
  return new Reaction("bot-user", data, options.isGroup ?? true);
}

test("normalizes group heart and like events", () => {
  assert.deepEqual(incomingReactionEvent(reaction(Reactions.HEART)), {
    event_type: "reaction",
    group_id: "group-reaction",
    reactor_id: "target-user",
    reactor_display_name: "Người cần phản hồi",
    reacted_at: "2026-06-24T07:31:19.518Z",
    reaction: "heart",
  });
  assert.equal(incomingReactionEvent(reaction(Reactions.LIKE))?.reaction, "like");
});

test("ignores other reactions, self reactions and direct-chat reactions", () => {
  assert.equal(incomingReactionEvent(reaction(Reactions.HAHA)), null);
  assert.equal(incomingReactionEvent(reaction(Reactions.HEART, { uidFrom: "0" })), null);
  assert.equal(
    incomingReactionEvent(reaction(Reactions.HEART, { isGroup: false })),
    null,
  );
});
