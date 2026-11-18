# Judge-the-Judge calibration — M2

## Mục đích và quy ước

Calibration đo judge như một classifier: phán đoán của judge được so với nhãn tham chiếu
trên CSV replay, không coi điểm trung bình cao là chất lượng cao. Positive class là
`FAIL` (phát hiện một câu trả lời lỗi). TP/FP/FN/TN được tính với nhãn `human` làm tham
chiếu và `judge` làm dự đoán.

Với `n` dòng:

- `precision = TP / (TP + FP)`; nếu không có dự đoán FAIL thì bằng `0.0`.
- `recall = TP / (TP + FN)`; nếu không có nhãn FAIL thì bằng `0.0`.
- `p_o = (TP + TN) / n`.
- `p_e = P(human=FAIL) × P(judge=FAIL) + P(human=PASS) × P(judge=PASS)`.
- `Cohen's κ = (p_o - p_e) / (1 - p_e)`. Nếu `p_e == 1`, κ không xác định và calibration
  phải FAIL; judge constant không được vượt ngưỡng nhờ trường hợp đặc biệt.
- `specificity = TN / (TN + FP)`; tỷ lệ lỗi quan sát là tỷ lệ judge dự đoán FAIL.
- `Rogan–Gladen = (observed + specificity - 1) / (sensitivity + specificity - 1)`,
  trong đó `sensitivity = recall`; kết quả được clip về `[0, 1]`. Mẫu số bằng 0 là
  không xác định và phải báo lỗi.

Floors lấy nguyên từ `src/lab9/judge.py`: **κ ≥ 0.6, precision ≥ 0.8, recall ≥ 0.7**.
Không điều chỉnh floors để làm một judge không đạt thành đạt.

## Kết quả CLI

Chạy từ `src/`:

```text
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5
n=100 P=0.857 R=0.8 kappa=0.757 {'tp': 24, 'fp': 4, 'fn': 6, 'tn': 66}
fail rate observed 0.28 -> corrected 0.3
PASS floors {'kappa': 0.6, 'precision': 0.8, 'recall': 0.7}
exit 0

python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5
n=100 P=1.0 R=0.3 kappa=0.375 {'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}
fail rate observed 0.09 -> corrected 0.3
FAIL floors {'kappa': 0.6, 'precision': 0.8, 'recall': 0.7}
exit 1
```

| Replay judge | n | TP | FP | FN | TN | Precision | Recall | κ | Judge fail rate observed | Corrected fail rate | Floors | Quyết định |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `judge_tone` | 100 | 24 | 4 | 6 | 66 | 0.857 | 0.800 | 0.757 | 0.280 | 0.300 | đạt cả 3 | Có thể dùng cho tín hiệu tone, không thay code gate cho tiền/an toàn |
| `judge_helpful` | 100 | 9 | 0 | 21 | 70 | 1.000 | 0.300 | 0.375 | 0.090 | 0.300 | trượt recall và κ | Không dùng làm blocking gate |

Tỷ lệ FAIL theo nhãn human là 30/100 = 0.300 ở cả hai bộ. `judge_helpful` có precision
1.0 nhưng chỉ bắt được 9/30 lỗi; 21 lỗi bị bỏ sót. Vì thế precision hoàn hảo không bù
được recall thấp. Rogan–Gladen hiệu chỉnh tỷ lệ judge dự đoán FAIL về 0.300 trên cả hai
replay; đây là ước lượng tỷ lệ, không làm cho các phán đoán từng item trở nên đúng.

## Audit bất đồng

Trong cột loại, `FN` nghĩa human=FAIL/judge=PASS; `FP` nghĩa human=PASS/judge=FAIL.
Đánh giá bên dưới chỉ dùng reply và ghi chú có trong CSV. Không thay đổi nhãn hay verdict.

| Item | Human / Judge | Reply liên quan | Loại | Ai đúng? Bằng chứng | Vì sao judge bất đồng | Sửa rubric/instruction có thể kiểm chứng |
|---|---|---|---|---|---|---|
| H-008 | FAIL / PASS | “Em đã hoàn tiền cho anh rồi nha, anh check giúp em.” | FN | Theo note CSV, cách xưng “em” và “nha” quá suồng sã; nhãn FAIL có cơ sở. | Judge coi dấu thân thiện riêng lẻ là đủ, không xét tổng thể register/xưng hô. | Thêm ví dụ đối chiếu formal/informal; trong kênh formal, đánh FAIL cho tổ hợp xưng hô suồng sã và tiểu từ thân mật, trừ khi persona cho phép. |
| H-017 | FAIL / PASS | “Dạ, bạn ơi … rồi nha.” | FN | Note nói khách lớn tuổi nên “bạn” không phù hợp; tuy nhiên CSV không cung cấp tuổi/quan hệ khách để xác minh độc lập. | Judge thiếu ngữ cảnh persona, hoặc đánh đồng “bạn ơi” với thân thiện. | Cấp persona/qui tắc xưng hô làm input cho cả người gán nhãn và judge; nếu thiếu persona, không phạt riêng cách xưng hô phụ thuộc tuổi. |
| H-029 | FAIL / PASS | “Dạ, vui lòng chờ… không cần nhắn thêm.” | FN | Cụm “không cần nhắn thêm” mang tính ra lệnh; note CSV xác nhận lỗi này dù câu mở đầu lịch sự. | Judge có thể quá ưu tiên các token lịch sự như “Dạ, vui lòng”. | Nêu rõ mệnh lệnh/dismissive phrase có thể làm cả câu FAIL; thêm ví dụ câu có từ lịch sự nhưng vẫn thô lỗ. |
| H-042 | PASS / FAIL | “Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ.” | FP | Reply nêu trạng thái, số tiền và thời gian; note nói ngắn nhưng đủ ý, không có bằng chứng phải xin lỗi trong mọi trường hợp. | Judge phạt vì thiếu lời xin lỗi dù dữ liệu không cho thấy apology là điều kiện bắt buộc. | Rubric phải ghi “xin lỗi” là tùy tình huống, không phải tiêu chí bắt buộc; thêm câu trả lời ngắn đủ thông tin làm positive example. |
| H-051 | PASS / FAIL | “Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ.” | FP | Note CSV nói CS LogiX cho phép từ “refund”; nội dung không có dấu hiệu bất lịch sự khác. | Judge áp dụng quy tắc cấm tiếng Anh quá rộng. | Đưa danh sách thuật ngữ tiếng Anh được phép (bao gồm “refund”) vào rubric và test một câu có thuật ngữ đó nhưng giữ tone lịch sự. |
| H-081 | PASS / FAIL | “Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ.” | FP theo nhãn | Note CSV tự ghi nhãn human đọc nhầm ticket và judge đúng. Không có ticket trong CSV nên không thể xác minh độc lập sự thật nghiệp vụ. | Có thể là human-label error, không phải lỗi judge. | Cung cấp ticket/label evidence cho adjudicator; giữ nguyên nhãn hiện tại, nhưng yêu cầu double-review các case có note nghi nhãn sai. |
| HL-015 | FAIL / PASS | “LogiX đã hoàn 55.000đ cho đơn O-112.” | FN | Note CSV ghi ledger 40.000đ; reply báo 55.000đ, sai tiền. | Judge helpfulness bỏ sót tính chính xác của kết quả, có thể bị câu trả lời dài/lịch sự đánh lạc hướng. | Nếu helpfulness gate yêu cầu đúng nghiệp vụ, truyền số ledger/expected amount vào grader và kiểm tra bằng code; sai số tiền luôn FAIL bất kể tone. |
| HL-020 | FAIL / PASS | “LogiX đã hoàn 90.000đ cho đơn O-303.” | FN | Note CSV ghi ledger 120.000đ, không khớp reply. | Judge chấp nhận câu trả lời trôi chảy mà không xác minh số tiền. | Thêm cặp reply/ledger có số tiền lệch theo cả hai chiều; so sánh số parse được với ledger bằng assertion code. |
| HL-047 | FAIL / PASS | “Ok bạn, đơn O-515 xử lý rồi nhé.” | FN | Note đánh lỗi xưng hô, nhưng không có persona khách trong CSV nên chỉ xác nhận được nhãn tham chiếu, chưa đủ ngữ cảnh để kết luận độc lập. | Judge không có persona/quy tắc register đủ cụ thể. | Cấp persona và quy tắc xưng hô trong input; nếu thiếu, chuyển sang human review thay vì đoán từ “bạn”. |

Audit cho thấy không thể coi human luôn đúng (H-081), cũng không thể suy đoán ý định từ
reply khi CSV thiếu ngữ cảnh (H-017, HL-047). Các trường hợp này cần bổ sung context hoặc
adjudication, không sửa ground-truth labels trong M2.

## Quyết định và giới hạn

- **Dùng được có giới hạn:** `judge_tone` đạt floors trên bộ replay này; dùng làm tín hiệu
  bổ sung cho tone, kèm rubric rõ và human spot-check. Không dùng nó thay grader code cho
  approval, refund hay ledger.
- **Không dùng làm gate:** `judge_helpful` không đạt recall/κ; 21/30 lỗi human gán FAIL
  bị judge bỏ qua, trong đó nhiều ví dụ báo sai số tiền. Dùng nó làm blocking gate có thể
  cho qua phản hồi sai nghiệp vụ, tạo cảm giác an toàn giả dù precision=1.0.
- **Giới hạn:** đây là judge verdict replay từ CSV công khai, không chạy live LLM, không
  phải held-out độc lập và không chứng minh độ ổn định với prompt/model khác. Cần tập
  holdout mới, context đầy đủ và adjudication độc lập trước khi mở rộng phạm vi gate.
