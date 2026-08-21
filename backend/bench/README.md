# Benchmark bộ phân loại mention

So sánh các model cho `mention_classifier`, đo **quyết định thật của pipeline**
(skip hay tag) chứ không chỉ độ chính xác nhãn — vì một lần skip sai làm rơi
một đầu việc, còn tag sai chỉ tốn thêm một tin nhắn.

```bash
backend/.venv/bin/python -m bench.mention_bench --repeats 3 --concurrency 3 --tau 0.65
backend/.venv/bin/python -m bench.mention_bench --only deepseek-v4-flash-nothink
```

- `mention_golden.jsonl` — 36 case / 39 target, viết tay bằng tiếng Việt, tập
  trung vào vùng mơ hồ mà rule không bắt được (rule đã chặn sẵn "ok"/"cảm ơn"
  trước khi tới AI), cộng 3 case prompt injection và 3 case multi-target.
- Bench import thẳng `CLASSIFIER_PROMPT` và `MentionClassificationResult` từ
  `app.services.mention_classifier`, và dựng payload y hệt `_prepare_job`, nên
  đo đúng prompt đang chạy production.
- Kết quả thô ghi ra `results.json`.

Chỉ số quan trọng nhất là **false skip** (ground truth cần trả lời nhưng model
skip). Cột `thieu decision` là fail-safe: thiếu decision thì production vẫn tag.
