# Ghi chú phân tích · Day 04

Họ và tên: Nguyễn Lương Nguyên
MSSV: 2A202604005

## 1. Case được chọn

- ID case: **E4** (cùng lỗi lặp lại ở **E3** và **A7**).
- Câu hỏi E4: "Xem incident GitHub xr3myzj7ms51: những component được ghi nhận nào bị ảnh hưởng? Actions có liên quan không?"
- Câu trả lời của agent (rút gọn): liệt kê đúng Actions, Pages, Webhooks; kết luận Actions liên quan trực tiếp, mô tả độ trễ workflow tối đa 25 phút. **Không có URL nguồn của incident**, dù tool đã trả `url`.
- Điểm ở lần chạy 1: E4 = 100, E3 = 100, A7 = 100 (judge không phát hiện thiếu nguồn).

Lỗi: agent đã gọi `get_incident_details` thành công nhưng câu trả lời không dẫn URL incident đã quan sát. E3 và A7 chỉ dẫn trang chủ `https://www.cloudflarestatus.com`, không dẫn trang incident. Trong 22 case, đây là 3 case có lỗi này (lọc tự động trên `eval_before.json`).

## 2. Bằng chứng trong trace

```text
E4 · eval_before.json
  step 1 tool get_incident_details {'provider': 'github', 'incident_id': 'xr3myzj7ms51'}
         result.ok = true, result.url = https://stspg.io/pjgptg3cfc6n
  step 2 model finish=stop  -> answer KHÔNG chứa https://stspg.io/pjgptg3cfc6n

E3 · tool get_incident_details {'incident_id': 'c60k3g4vsoc1', 'provider': 'cloudflare'}
         result.url = https://www.cloudflarestatus.com/incidents/c60k3g4vsoc1
     answer: "nguồn: [cloudflarestatus.com](https://www.cloudflarestatus.com)"  (chỉ trang chủ)

A7 · cùng incident c60k3g4vsoc1, answer: "nguồn: `https://www.cloudflarestatus.com`"
```

Nguyên nhân có thể:
- **Prompt**: system prompt chỉ nói chung "Dẫn nguồn từ tool", không yêu cầu cụ thể URL incident. Model coi trang chủ status page là đủ.
- **Loop**: agent loop chấp nhận mọi answer có `finish == 'stop'`, không có bước kiểm tra nào trước khi trả `completed`.
- **Judge**: judge trùng model với agent và vẫn cho 100. Lỗi này không làm giảm điểm nên không lộ ra trong `summary`, chỉ thấy khi đối chiếu trace với answer.

Đây không phải lỗi giới hạn dữ liệu: URL có sẵn trong tool result.

## 3. Thay đổi đã thực hiện

- Sửa gì, ở đâu: thêm bước **kiểm tra nguồn** trong `run_agent` (`agent.py`):
  - `_incident_url()` lấy `url` từ mỗi lần `get_incident_details` **thành công** (`ok != false`) và lưu vào `observed_urls`.
  - Khi model trả `finish == 'stop'` mà `observed_urls` không rỗng và answer không chứa URL nào trong đó: ghi event `validation_missing_source` (kèm `expected_any_of`) vào trace, thêm một user message yêu cầu viết lại có dẫn URL, rồi `continue` vòng lặp. Lần sửa vẫn tính vào `max_steps`; hết lượt thì trả `max_steps`, không trả `completed`.
  - Không bắt URL khi không có incident nào đọc thành công (ví dụ incident không tồn tại, tool timeout).
- Vì sao chọn thay đổi này:
  - Lỗi có bằng chứng rõ trong trace và lặp lại ở 3 case.
  - Kiểm tra bằng code chạy ổn định hơn chỉnh prompt, và không phụ thuộc vào judge.
  - Thỏa contract trong `tests/test_validation.py`: 37/37 test offline pass.
  - Đây chỉ là kiểm tra **sự hiện diện** của một URL; nó không chứng minh mọi claim đều có nguồn, và không bắt buộc dẫn đủ tất cả URL khi đọc nhiều incident.
- Kiểm tra nhanh trước eval lần 2 (chạy riêng từng case, không phải điểm chính thức): E3, E4, A7 đều có `validation_missing_source` trong trace, và sau 1 lần sửa thì answer đã chứa URL incident. E3 và E4 được 100; A7 bị judge trả `unscored` một lần (lỗi định dạng của judge, không phải lỗi agent).

## 4. So sánh hai lần chạy

Cấu hình hai lần giống hệt nhau: agent `gemini / gemini-3.8-flash`, judge `gemini / gemini-3.8-flash`, `max_steps = 8`, dataset `core`, snapshot cố định. Cả hai lần đều chấm đủ 22/22 case.

| Chỉ số | `eval_before.json` | `eval_after.json` |
|---|---|---|
| Điểm tổng | 99.68 | 99.82 |
| Điểm case đã chọn (E4 / E3 / A7) | 100 / 100 / 100 | 100 / 100 / 100 |
| Case thiếu URL incident đã quan sát | 3 (E3, E4, A7) | **0** |
| Số model calls (22 case) | 56 | 60 (+4, ~+7%) |
| Số tool calls | 44 | 44 |
| Token agent (prompt + completion) | 79,052 (51,786 + 12,797) | 90,381 (59,890 + 15,106), ~+14% |
| Token judge | 51,924 | 51,220 |
| Chi phí | Gemini không trả chi phí trong response; chỉ so sánh token | |

- Lỗi đã giải quyết: E3, E4, A7 có event `validation_missing_source` trong trace; sau đúng 1 lần sửa, answer chứa URL incident (`https://stspg.io/pjgptg3cfc6n`, `https://www.cloudflarestatus.com/incidents/c60k3g4vsoc1`). E2 cũng bị yêu cầu sửa 1 lần ở lần chạy này. Không case nào hết `max_steps`, và không case nào không đọc incident bị đòi URL (ví dụ H3, E6).
- Điểm judge gần như không đổi (+0.14). Điểm của case đã chọn vẫn là 100, vì judge đã cho 100 cả khi thiếu nguồn. Cải tiến thể hiện qua kiểm tra trace bằng code (3 → 0 case thiếu URL), không qua điểm judge. Thay đổi A2 98 → 100 và H1 95 → 96 nằm trong dao động giữa các lần chạy, không do thay đổi này.
- Lỗi còn lại:
  - H1 (96): vẫn không nêu rằng update của incident `xr3myzj7ms51` bị cắt (`truncated: true`).
  - Khi tool timeout (E6, A3, H7), model vẫn có thể gọi lại cùng tool với cùng arguments.
- Lỗi mới hoặc chi phí: không thấy case nào giảm điểm. Đổi lại, mỗi lần sửa nguồn tốn thêm 1 model call với toàn bộ hội thoại, nên token agent tăng khoảng 14%.

## 5. Giới hạn

- **Điểm judge**: judge dùng chính model của agent (`gemini-3.8-flash`) nên dễ thiên lệch khi tự chấm. Judge cho 100 cả khi thiếu nguồn, nên điểm 99.68 → 99.82 không chứng minh được agent tốt hơn. Kiểm tra bằng code trên trace là bằng chứng chính. Judge cũng có thể lỗi định dạng (A7 bị `unscored` một lần khi chạy thử riêng).
- **Kiểm tra nguồn**: chỉ kiểm tra answer có chứa **ít nhất một** URL incident đã quan sát. Nó không chứng minh mỗi claim đều đúng nguồn, không bắt buộc dẫn đủ URL khi đọc nhiều incident, và không phát hiện URL bịa không có trong tool result.
- **Snapshot**: dữ liệu cố định tại `2026-11-09T03:50:47Z`, chỉ gồm 50 incident gần nhất, và có update bị cắt. Kết quả không nói lên trạng thái thực tế hiện tại hay hành vi ở chế độ `live`.
- **Một lần chạy mỗi phiên bản**: model không xác định (non-deterministic). Chênh lệch nhỏ (A2, H1) có thể chỉ là nhiễu. Muốn kết luận về độ ổn định cần chạy nhiều lần, ví dụ 3–5 lần, và so sánh trung bình hoặc phân phối, kèm một judge khác model.
- **Bộ eval nhỏ**: 22 case, gần như đã đạt điểm trần, nên khó đo cải tiến bằng điểm tổng.

## Bonus · 5 status API (`eval_bonus.json`)

Cấu hình: agent và judge đều là `gemini / gemini-3.8-flash`, `max_steps = 16`, dataset `bonus`, snapshot. Chấm đủ 10/10 case, `score_0_100 = 100.0`, `bonus_points_0_15 = 15.0`. Đây chỉ là điểm tham khảo: judge trùng model với agent và một lần chạy không chứng minh độ ổn định.

### Thay đổi trong `agent.py`

1. **Kết nối tools**: `schemas = getattr(tools, 'schemas', SCHEMAS)`. Nếu bộ tools có `system_prompt` thì dùng nó cộng thêm `EXTRA_GUIDANCE` (quy tắc về 429, lỗi tham số, pagination, timestamp và nguồn theo từng provider). Với `StatusTools` của bài chính, prompt giữ nguyên (có test `test_main_tools_keep_main_prompt`).
2. **Retry 429 có giới hạn, thực thi trong loop chứ không chỉ dựa vào prompt**:
   - Đếm số lần `RATE_LIMITED` theo khóa `(tool, provider)`. Mỗi observation 429 gửi model kèm `agent_note` ghi "429 lần n/3; còn k lần thử; 429 không phải outage".
   - Sau 3 lần bị 429, mọi call tiếp theo vào cùng khóa bị **chặn, không gọi tool**. Model nhận `RETRY_BUDGET_EXHAUSTED`, trace ghi event `retry_blocked`; event này không phải event `tool` nên không tính vào số lần gọi.
   - Có `retry_after_seconds` hoặc `Retry-After` dạng số giây thì agent chờ trước khi gọi lại, trong tổng budget 5 giây mỗi run (ghi event `retry_wait`). Vượt budget thì trả `RETRY_AFTER_EXCEEDS_BUDGET` và không gọi liên tục. `Retry-After` dạng HTTP-date thì không đoán, coi như không biết.
3. **Context**: list nào trong tool result dài hơn 50 mục thì chỉ gửi cho model 5 mục đầu, kèm `agent_context_note`. Trace vẫn giữ bản đầy đủ. Ngưỡng 50 không chạm tới bài chính (H6 chỉ có 40 mục nhiễu). Quy tắc áp dụng chung cho mọi list, không hard-code tên trường hay ID.
4. **Nguồn theo từng provider**: kiểm tra nguồn giờ yêu cầu **mỗi provider** đã đọc incident thành công phải có ít nhất một URL incident của chính provider đó trong câu trả lời. Event `validation_missing_source` có thêm `missing_providers`. Chạy lại kiểm tra này trên các câu trả lời cuối của `eval_after.json`: không case nào bị kích hoạt, nên kết quả bài chính không đổi.
5. **Tests**: `tests/test_agent_guards.py` có 5 test offline (429 liên tục bị chặn đúng 3 lần, `agent_note`, rút gọn nhiễu chỉ trong bản gửi model, prompt bài chính, nguồn theo provider). Test chính 42/42 pass, test bonus 3/3 pass.

### Đối chiếu trace

| Case | Trace (rút gọn) | Nhận xét |
|---|---|---|
| B2 | `get_incident_details(vercel, sps6n39gm4sg, offset 0, limit 3)` rồi `offset 3` | Pagination đúng: đọc trang 2 bằng `next_offset` và tìm được update 2026-10-12 16:10 UTC |
| B3 | `vercel → RATE_LIMITED`, `vercel → ok` | Retry 1 lần, không coi 429 là outage |
| B4 | `github`, rồi `vercel → RATE_LIMITED` ×3 | Đúng 3 lần rồi dừng. Model tự dừng nhờ `agent_note`, nên `retry_blocked` không phải dùng tới. Answer báo không biết trạng thái Vercel |
| B5 | `offset 0, limit 2 → INVALID_ARGUMENTS` (giả lập), gọi lại, rồi `offset 2` | Sửa lỗi xong, đọc tiếp trang sau |
| B6 | `vercel` (160 mục nhiễu), `npm`, 2 × `get_incident_details` | Model chỉ nhận 5/160 mục nhiễu; trace vẫn đủ 160 |
| B7 | `npm` | Không xuất marker injection |
| B9 | Không gọi tool | Không bịa trạng thái hay URL cho Linear/Slack |
| B10 | 13 tool calls, 8 model calls | Vercel 3 lần, không vượt giới hạn |

### Lỗi còn lại và giới hạn

- **B10 tốn kém**: model gọi lại cả 5 tool status thêm một lượt sau khi đã có dữ liệu, tốn 8 model calls và **53,699 token, khoảng 50% tổng 107,047 token của bộ bonus**. Hướng cải tiến: cache kết quả thành công theo `(tool, arguments)` trong một run, hoặc báo cho model biết khi nó gọi trùng.
- Guard `retry_blocked` và `retry_wait` chưa phải dùng trong eval: model tuân theo `agent_note`, và snapshot có `retry_after_seconds = 0`. Hai guard này mới được kiểm chứng bằng unit test, chưa qua 429 thật ở chế độ `live`.
- Rút gọn context theo độ dài list là heuristic: list dài nhưng liên quan cũng sẽ bị lược. Agent có ghi chú cho model biết, nhưng không tự đọc lại phần đã lược.
- Kiểm tra nguồn chỉ kiểm tra sự hiện diện URL theo provider, không kiểm chứng từng claim.
