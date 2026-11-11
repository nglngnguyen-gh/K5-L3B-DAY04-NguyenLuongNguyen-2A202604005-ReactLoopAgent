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
