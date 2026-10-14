# Báo cáo bản duyệt TaskKit.vn Windows Computer Bridge MCP

Ngày kiểm: 2026-10-14. Bản source candidate: **0.4.2.dev0**. Đây là bản reviewable trong môi trường Linux, chưa được xác nhận vận hành trên Windows thật/CAD/GPU. Chưa push, tạo PR/release, đăng diễn đàn, thay cấu hình Codex hoặc tác động máy Windows người dùng.

## Phạm vi và baseline

- Repo `/workspace/taskkit-windows-computer-mcp`; origin `Longtran2404/taskkit-windows-computer-mcp`.
- HEAD ban đầu đúng `92cfa9b40c33e04f49ab01d7df5b947cd552a8f7`; nhánh `work`, working tree sạch. Không có thay đổi có sẵn để ghi đè; không stash/reset/clean.
- Đã đọc và tuân AGENTS.md. Giữ Apache-2.0, LICENSE, NOTICE, TaskKit.vn và attribution Minh Long Tran. Mọi thay đổi trên nhánh local `review/safety-reliability-20261014`.
- Baseline Linux Python 3.12.14: **12 passed, 4 skipped**, MCP stdio đủ 14 tools/status. Ban đầu thiếu pytest; đã tạo venv riêng ngoài repo và cài dependencies, không dùng elevation.
- `.github/workflows/tests.yml` định nghĩa Windows/Ubuntu × Python 3.11/3.13. Kiểm API GitHub để xác nhận lại CI bị proxy HTTP 403; không dùng nhận định “CI đang xanh” làm bằng chứng xác minh độc lập.

## Thay đổi

| Vấn đề | Hành vi candidate |
| --- | --- |
| PrintWindow có thể treo | Spawn worker dùng một lần, deadline 3 giây gồm startup/kết quả; terminate rồi kill với join hữu hạn. Không timeout thread để native tiếp tục treo. Không nhận kết quả muộn; crash/no-result không có ảnh/token. Không kill được worker thì latch stop và yêu cầu dừng process cục bộ. |
| UIA có thể block | Inspect/read/set/invoke cô lập trong worker 3 giây; guard khi đợi, ngay trước mutation, và sau mutation/kết quả. Stop phát hiện ở child truyền latch về parent. Timeout/abort mutation có thể có effect không xác định. |
| Ảnh/token stale | Kiểm stop, HWND/PID/process creation identity, rect/DPI và kích thước PNG trước phát ảnh/token, kể cả sau encode. Token 90 giây, một lần mutation, có DPI. Không fallback desktop. |
| Clamp / overlay / focus steal | GetCursorPos thực phải khớp tọa độ dự định; hit-test chính point thực. Guard stop/identity/rect/DPI/focus/cursor/input held trước mỗi event và từng đoạn wait. |
| Hold/drag/click/Ctrl+A thiếu guard | Transaction chung cho chuột, chord và UTF-16 typing; waits ngắt được. Ctrl+A recheck giữa từng down/up. Cleanup chỉ release successful downs của transaction. |
| Key-up cập nhật trễ | Đợi state settle tối đa 150 ms trước effect tiếp theo, tiếp tục guard. Không gửi lặp release đã thành công. State không settle thì abort. |
| Stop / preview rearm | Stop permanent cho mọi mode, capture/UIA/input. Parent stop đóng shared event của preview; worker bị cancel. Opening preview không clear stop. Sửa race publication/ready và giữ chẩn đoán startup từ child. |
| Session tự arm bằng config | Native owner dialog local, grant tối đa 5 phút và bound allowlist/mode. Status/capture/read không arm. Expiry/config change yêu cầu consent mới. MCP không có resume/arm tool. Input vẫn disabled mặc định; mutation vẫn dry-run mặc định. |
| CRLF bị universal-newline | So sánh exact UTF-8 bytes, nhận optional BOM. Giữ CRLF/LF, Vietnamese/emoji/U+FEFF; exclusive create, không overwrite differing files hoặc race winner. Đọc buffer lại sau consent. |
| Chẩn đoán / đóng gói | Capture/status có capability, uncertainty, timestamp, DPI/origin. Runtime MCP errors structured + isError. Smoke assertions thực; docs Anh/Việt và checklist Windows. Installer chọn interpreter và mang LICENSE/NOTICE; source manifests đầy đủ. Local-only checks từ chối UNC/device/ADS/mapped-network và kiểm canonical drive path. |

## Kết quả kiểm

| Kiểm tra | Kết quả | Loại bằng chứng |
| --- | --- | --- |
| Baseline pytest Python 3.12.14 | 12 passed, 4 skipped | Linux thật; backend giả lập/skip Win32 |
| Regression Python 3.12.14, 3 lần | 150 passed, 2 skipped mỗi lần | Linux thật; fake adapters/Win32 guard bodies, real disposable subprocesses |
| Regression Python 3.13.5, 3 lần | 150 passed, 2 skipped mỗi lần | Linux thật; cùng giới hạn backend |
| Stdio smoke trên 3.12 và 3.13 | PASS, 14 tools | Process stdio MCP thật; disabled/unarmed status, schema/dry-run defaults, structured error + isError; không capture/input thật |
| Independent read-only review | Đã hoàn tất; snapshot review chạy 136 passed, 2 skipped + smoke | Agent riêng, không edit/input; phát hiện stop propagation, preview races, late decode, key-up delay, DPI/path/license gaps đã sửa và thêm regression |
| Build sdist/wheel, inventory LICENSE/NOTICE/source | PASS | Linux packaging thật; source gồm tests/fakes/scripts/docs |
| Install wheel ngoài checkout, import + stdio smoke | PASS | Linux cài wheel thật trong venv riêng; không editable fallback |
| Dependency checks, compileall, diff whitespace | PASS | Kiểm tĩnh/packaging Linux |
| Windows DLL ABI / Win32 Esc adapter | 2 skipped | Cần Windows; test adapter Esc khi chạy Windows vẫn là mock |
| Windows desktop/COM/PrintWindow/SendInput/Tkinter/PowerShell | Chưa chạy | Không có Windows desktop/PowerShell trong cloud |
| Python 3.11 và matrix CI remote | Chưa chạy/xác minh lại | Không có interpreter 3.11; GitHub API proxy 403 |
| CAD/GPU/WGC | Chưa kiểm, WGC chưa triển khai | Không cấp claim tương thích |

Dependencies được cài trong venv review: MCP 1.30.0, Pillow 12.3.0, pytest 9.1.1. Các bản cụ thể và output đầy đủ nằm trong artifact logs/snapshot. Bảng regression là kết quả cuối cùng của các lệnh được ghi log; xem artifact manifest cho commit và hashes.

Các test bao phủ clamp, focus/overlay, stop mọi guard stage của mouse/chord/text, resize/DPI/negative monitor/process identity, modifiers và cleanup ownership, async key-up, Ctrl+A focus steal, Vietnamese/emoji, CRLF/LF/BOM/leading U+FEFF/existing-file/create race, capture timeout/crash/late result/no image/token, shared preview stop/start races, UIA guard/password/duplicate IDs, consent expiry/config change, MCP structured errors và default disabled/dry-run. Worker tests chạy **spawn processes thật trên Linux** với synthetic hang/crash; chúng không gọi PrintWindow hay COM.

`tests/test_native_guards.py` compile nguyên body một số guard từ source với fake Win32 objects để kiểm control flow trên Linux; không chứng minh ctypes ABI hoặc semantics native. `tests/fakes.py` được ghi rõ fake, không bypass native checks trong production.

## Giới hạn còn lại

1. Không có Windows thật. Bộ cài PowerShell, COM providers, mixed DPI/borders, focus restrictions, swapped mouse buttons, touch/pen, UIPI/elevated apps, handle/memory behavior và performance cold-start cần checklist riêng. Session dialog/cancellation cũng chưa được quan sát trực tiếp trên Windows.
2. GetAsyncKeyState không nhận diện nguồn physical/injected. Khi người dùng nhấn cùng phím/nút transaction đang giữ, cleanup ownership có thể không phân biệt được physical hold mới. Preheld/unrelated input được guard; không tuyên bố giải quyết hoàn toàn same-code provenance. Cần desktop riêng hoặc app API nếu yêu cầu đó bắt buộc.
3. Checks và SendInput không atomic; có khe race rất ngắn giữa kiểm và event. Polling không bảo đảm bắt xung Esc/F12 quá ngắn hay thao tác khi đổi Windows desktop. Stop đã phát hiện latch permanent; dùng held stop/close/process termination cục bộ khi cần.
4. HWND/PID/process creation chống process/PID reuse; Windows không cung cấp creation timestamp chuẩn cho một HWND. Reuse HWND trong cùng process và thay đổi nội dung trong rect không đổi không được chứng minh bởi token.
5. Nonuniform PNG không chứng minh viewport GPU đúng/current. Mapping check xác nhận awareness/DPI/pixel dimensions, không chứng nhận image-to-viewport correctness. WGC chưa tích hợp; không whole-desktop fallback.
6. UIA đã dispatch có thể tiếp tục tác động app sau worker timeout/kill; file write/input cũng có thể hoàn thành một phần trước stop. Error báo effects chưa được xác minh; inspect UI/file trước retry. Không dùng invoke/input success làm completion proof.
7. Deadline không phải realtime guarantee: có terminate/kill cleanup tối đa 0.5 giây và OS scheduling/process-start/guard overhead. Cold COM/module generation hoặc frame lớn có thể fail an toàn với deadline 3 giây.
8. Canonical drive/path checks không phải filesystem sandbox; junction/reparse có race và filesystem I/O có thể chậm. Matching existing files chỉ được đọc; differing files/exclusive-create winners được bảo toàn. UIA save là bản sao, không save cửa sổ gốc.
9. Wheel Linux smoke xác nhận package/protocol/dependencies, không thể xác nhận comtypes Windows dependency hoặc Windows installer.

## Bằng chứng và duyệt

Thư mục artifact: `/workspace/taskkit-review-artifacts`. Có `review.patch`, `source.zip`, `source.tar.gz`, packages/wheel/sdist, `manifest.json`, `SHA256SUMS`, report/checklist bản copy và logs baseline/regression/smoke/build/install/dependency. Commit local và base commit được ghi trong manifest; patch áp dụng từ base được kiểm bằng một checkout tách biệt. Source archives tạo từ commit, không chứa venv, dependencies, config cá nhân, credential, screenshot hay user documents.

Reproduce trong checkout source: `python -m pip install -e ".[test]"`, `python -m pytest -q`, `python scripts/smoke_test.py`, `python -m build`. Chạy Windows checklist với chủ máy trước khi cập nhật GitHub/chia sẻ diễn đàn. Không cần duyệt để tiếp tục đọc/test Linux; hành động xuất bản vẫn chưa được thực hiện.

## Cơ sở Win32 đã đối chiếu

- [PrintWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-printwindow): synchronous/blocking, do đó cô lập process.
- [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput): trả số event đã chèn và chịu UIPI; không dùng làm chứng nhận UI completion.
- [GetAsyncKeyState](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getasynckeystate): high bit phản ánh held state; recent-press low bit có thể bị caller khác lấy nên polling có giới hạn.
- [GetWindowRect](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowrect): DPI virtualization/invisible borders cần kiểm mapping thực.
- [SetCursorPos](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setcursorpos): ClipCursor có thể điều chỉnh tọa độ, cần GetCursorPos trước hit-test/event.
