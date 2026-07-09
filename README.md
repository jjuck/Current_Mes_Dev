# Current Measure Program

웹 기반으로 동작하는 소비전류 독립 검사 프로그램입니다. QR 또는 S/N 입력을 기준으로 제품 연결 시점을 감지하고, 모드별 검사 절차를 수행한 뒤 결과를 저장합니다. 현재는 실시간 상태 동기화를 위해 WebSocket 기반 UI 업데이트를 사용합니다.

## 1. 프로젝트 개요

이 프로젝트는 현장 검사 PC에서 다음 흐름을 자동화하기 위해 작성되었습니다.

1. 작업자가 QR 또는 S/N을 입력합니다.
2. 계측기에서 원시 소비전류를 짧은 주기로 폴링합니다.
3. 원시값이 임계값 이상으로 연속 감지되면 모드별 검사 절차를 진행합니다.
4. 모드에 따라 SigmaStudio 다운로드를 수행하거나 생략합니다.
5. 모드별 대기 시간 후 최종 소비전류를 읽습니다.
6. PASS 또는 FAIL 판정 후 로그 CSV에 저장합니다.
7. 브라우저 UI는 WebSocket으로 백엔드 상태를 실시간 반영합니다.

## 2. 주요 기능

- 로컬 웹 대시보드 UI
- COM 포트 자동 감지 및 상태 표시
- 제품 연결 감지 트리거
- SigmaStudio 자동 Link/Compile/Download 연동
- 4개 측정 모드 지원
- WebSocket 기반 실시간 상태 반영
- PASS 또는 FAIL 판정
- 최근 기록 및 로그 CSV 저장
- 포터블 배포 실행 지원

## 3. 지원 모드

모드 정의는 [`build_measurement_mode_specs()`](src/current_daemon/config.py:12) 기준입니다.

### 3.1 [`Digital`](src/current_daemon/domain.py:74)
- 계열: Digital
- SigmaStudio 다운로드: 사용
- 측정 전 대기: `5초`
- 공정 상한: `25.00mA` (`raw 2500`)

### 3.2 [`Analog`](src/current_daemon/domain.py:66)
- 계열: Analog
- SigmaStudio 다운로드: 미사용
- 측정 전 대기: `1초`
- 공정 상한: `10.00mA` (`raw 1000`)

### 3.3 [`ANCR MIC`](src/current_daemon/domain.py:69)
- 계열: Analog
- SigmaStudio 다운로드: 미사용
- 측정 전 대기: `1초`
- 공정 상한: `19.00mA`

### 3.4 [`ANCR Sensor`](src/current_daemon/domain.py:72)
- 계열: Digital
- SigmaStudio 다운로드: 사용
- 측정 전 대기: `5초`
- 공정 상한: `30.00mA`
- 표시값 계산과 PASS/FAIL 판정 모두 `1/2` 계산 계수 적용

## 4. 공통 트리거 조건

모든 모드는 동일한 제품 연결 감지 규칙을 사용합니다.

- 원시값 `100` 이상
- `3회 연속` 감지

핵심 로직은 [`_wait_for_download_trigger()`](src/current_daemon/service.py:185) 에 있습니다.

## 5. 현재 동작 흐름

핵심 흐름은 [`MeasurementRecorder.measure_and_log()`](src/current_daemon/service.py:81) 에 있습니다.

1. [`POST /api/measurements`](src/current_daemon/web_api.py:102) 요청 수신
2. 입력된 모드 기준으로 세션 시작
3. 트리거 조건이 충족될 때까지 폴링
4. 모드가 Digital 계열이면 SigmaStudio 다운로드 수행
5. 모드별 대기 시간 적용
6. 최종 소비전류 측정
7. 모드별 상한과 계산 계수 기준으로 PASS 또는 FAIL 판정
8. 로그 CSV 저장
9. WebSocket으로 프런트에 상태 브로드캐스트

## 6. 표시값과 판정값 계산

표시값 계산은 [`CurrentReading.as_display_text()`](src/current_daemon/domain.py:42) 와 [`MeasurementThreshold.classify()`](src/current_daemon/domain.py:120) 를 기준으로 동작합니다.

- 기본 계산: `raw / 100`
- [`ANCR Sensor`](src/current_daemon/domain.py:72) 는 계산 계수 `0.5` 적용

예시:

- raw `1000` → 일반 모드 표시 `10.00mA`
- raw `5000` → [`ANCR Sensor`](src/current_daemon/domain.py:72) 표시 `25.00mA`

## 7. 로그 스키마

로그 파일은 `logs/<type>/<YYMMDD>/<YYMMDD>_Current_<type>.csv` 형식으로 저장됩니다.
예: [`logs/ANCRSensor/260615/260615_Current_ANCRSensor.csv`](logs/ANCRSensor/260615/260615_Current_ANCRSensor.csv)

현재 컬럼 순서:

- `datetime`
- `SN`
- `result`
- `raw_current`
- `current_mA`
- `type`
- `spec`
- `Vop`

규칙:

- `SN`: 입력된 시리얼 번호
- `type`: 드롭다운 표시명 그대로
  - `Digital`
  - `Analog`
  - `ANCR MIC`
  - `ANCR Sensor`
- `spec`: 현재 모드 공정 상한 `mA` 문자열
- `Vop`: 고정값 `8`
- `raw_current`, `current_mA`, `result`: 측정 결과

관련 직렬화 로직:

- [`MeasurementRecord.to_row()`](src/current_daemon/domain.py:168)
- [`MeasurementCsvLogger`](src/current_daemon/logger.py:13)

## 8. 실행 방법

### 8.1 개발 환경 실행

1. 의존성을 설치합니다.

```bash
python -m pip install -r requirements.txt
```

2. 앱을 실행합니다.

```bash
python app.py
```

3. 기본 브라우저가 자동으로 열립니다.

기본 주소는 [`http://127.0.0.1:8000`](http://127.0.0.1:8000) 입니다.

## 9. 포터블 배포 실행

포터블 배포본은 [`../Current_Mes_SW/run.bat`](../Current_Mes_SW/run.bat) 기준으로 실행합니다.

```bat
run.bat
```

현재 포터블 실행 스크립트는 marker 파일에 의존하지 않고, **매 실행 전** [`../Current_Mes_SW/requirements.txt`](../Current_Mes_SW/requirements.txt) 기준으로 포터블 Python 의존성을 동기화합니다.

즉, 기존 폴더를 재사용해도 최신 requirements 기준으로 재평가됩니다.

## 10. 주요 파일 구조

### 실행 진입점
- [`app.py`](app.py): 웹 서버 실행 진입점

### 백엔드 핵심 모듈
- [`src/current_daemon/config.py`](src/current_daemon/config.py): 운영 설정 및 모드 스펙
- [`src/current_daemon/service.py`](src/current_daemon/service.py): 측정 흐름, 트리거 감지, 모드 분기, SigmaStudio 연동
- [`src/current_daemon/serial_reader.py`](src/current_daemon/serial_reader.py): 계측기 시리얼 통신 및 COM 상태 확인
- [`src/current_daemon/web_api.py`](src/current_daemon/web_api.py): FastAPI 라우트 및 WebSocket 엔드포인트
- [`src/current_daemon/status_service.py`](src/current_daemon/status_service.py): 세션 상태, WebSocket 브로드캐스트, 최근 기록 관리
- [`src/current_daemon/logger.py`](src/current_daemon/logger.py): CSV 로깅 및 레거시 로그 정규화
- [`src/current_daemon/sigma_studio.py`](src/current_daemon/sigma_studio.py): SigmaStudio 연동 래퍼

### 프런트엔드
- [`web/index.html`](web/index.html): 메인 대시보드
- [`web/app.js`](web/app.js): WebSocket 구독, 상태 렌더링, 측정/취소 요청
- [`web/styles.css`](web/styles.css): 스타일 정의
- [`web/assets/logo.png`](web/assets/logo.png): 브랜드 로고

### SigmaStudio Fallback
- [`tools/sigma_downloader/SigmaDownloader.cs`](tools/sigma_downloader/SigmaDownloader.cs): C# 콘솔 앱 소스
- [`SigmaDownloader.exe`](SigmaDownloader.exe): Fallback 실행 파일

### 로그 및 테스트
- `logs/<type>/<YYMMDD>/<YYMMDD>_Current_<type>.csv`: 측정 로그
- [`tests/`](tests): 자동화 테스트

## 11. 주요 설정 위치

운영 설정은 [`build_config()`](src/current_daemon/config.py:82) 에서 조정합니다.

대표 항목:

- [`serial_settings.port`](src/current_daemon/config.py:51): COM 포트 고정값, 없으면 자동 감지
- [`default_measurement_mode`](src/current_daemon/config.py:65)
- [`download_trigger_raw_value`](src/current_daemon/config.py:70)
- [`download_trigger_confirm_count`](src/current_daemon/config.py:71)
- [`trigger_poll_interval_seconds`](src/current_daemon/config.py:72)
- [`input_refocus_delay_seconds`](src/current_daemon/config.py:74)
- [`measurement_mode_specs`](src/current_daemon/config.py:69)
- [`sigma_studio_dll_path`](src/current_daemon/config.py:77)
- [`sigma_downloader_executable_path`](src/current_daemon/config.py:78)

## 12. COM 포트 동작

COM 포트 감지는 [`WatanabeA7212Reader`](src/current_daemon/serial_reader.py:23) 에서 처리합니다.

- 설정에 포트가 지정되면 해당 포트를 우선 사용합니다.
- 지정되지 않으면 [`comports()`](src/current_daemon/serial_reader.py:8) 결과 중 `serial` 문자열이 포함된 포트만 자동 탐색 후보로 사용합니다.
- UI 상태 배지에는 `COM4 CONNECTED` 같은 형식으로 실제 포트명이 표시됩니다.

## 13. SigmaStudio 연동

SigmaStudio 연동은 2가지 경로를 지원합니다.

### 13.1 Pythonnet 직접 호출
- [`src/current_daemon/sigma_studio.py`](src/current_daemon/sigma_studio.py)
- [`pythonnet`](requirements.txt) 기반

### 13.2 Fallback C# CLI
- [`SigmaDownloader.exe`](SigmaDownloader.exe)
- Pythonnet 사용이 실패하거나 비트 충돌이 발생하면 fallback CLI 실행

## 14. 상태 동기화

프런트는 더 이상 자체 하드코딩 타이머를 계산하지 않고, 백엔드 상태를 source of truth 로 사용합니다.

- 초기 상태 조회: [`GET /api/status`](src/current_daemon/web_api.py:89)
- 실시간 상태 반영: WebSocket 상태 스트림
- 프런트 렌더링: [`web/app.js`](web/app.js)

이 구조 덕분에 `WAITING`, `MEASURING`, `COMPLETED`, `CANCELLED`, `ERROR` 상태와 남은 시간이 실제 백엔드 진행과 일치합니다.

## 15. 테스트

전체 테스트 실행:

```bash
python -m pytest -q
```

주요 테스트 파일:

- [`tests/test_app.py`](tests/test_app.py)
- [`tests/test_domain.py`](tests/test_domain.py)
- [`tests/test_serial_reader.py`](tests/test_serial_reader.py)
- [`tests/test_service.py`](tests/test_service.py)
- [`tests/test_sigma_studio.py`](tests/test_sigma_studio.py)
- [`tests/test_status_service.py`](tests/test_status_service.py)
- [`tests/test_web_api.py`](tests/test_web_api.py)

## 16. 운영 팁

- SigmaStudio는 동일 PC에서 실행 중이어야 합니다.
- 포터블 배포 시에는 최신 [`app.py`](app.py), [`src/`](src), [`web/`](web), [`requirements.txt`](requirements.txt), [`../Current_Mes_SW/run.bat`](../Current_Mes_SW/run.bat) 을 함께 반영해야 합니다.
- Edge 캐시 문제를 줄이기 위해 실행 시 브라우저는 timestamp 쿼리스트링을 붙여 자동 오픈됩니다.

## 17. 참고 자료

- UI 참고 시안: [`design/screen.png`](design/screen.png)
- 디자인 시스템: [`design/DESIGN.md`](design/DESIGN.md)
- 초기 레이아웃 참고: [`design/code.html`](design/code.html)
