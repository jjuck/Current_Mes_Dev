# Current Measure Program

웹 기반으로 동작하는 소비전류 독립 검사 프로그램입니다. QR 스캔을 기준으로 제품 연결 시점을 감지하고, SigmaStudio 다운로드를 수행한 뒤 최종 소비전류를 측정하여 로그를 남깁니다.

## 1. 프로젝트 개요

이 프로젝트는 현장 검사 PC에서 다음 흐름을 자동화하기 위해 작성되었습니다.

1. 작업자가 QR 또는 S/N을 입력합니다.
2. 계측기에서 원시 소비전류를 짧은 주기로 폴링합니다.
3. 원시값이 임계값 이상으로 연속 감지되면 SigmaStudio 다운로드를 실행합니다.
4. 다운로드 후 지정 시간만큼 대기합니다.
5. 최종 소비전류를 다시 읽어 PASS 또는 FAIL 판정 후 로그 CSV에 저장합니다.
6. 브라우저 UI에서 최신 측정 상태, COM 상태, 최근 기록을 확인합니다.

## 2. 주요 기능

- 로컬 웹 대시보드 UI
- COM 포트 자동 감지 및 상태 표시
- 원시값 기준 트리거 감지
- SigmaStudio 자동 Link/Compile/Download 연동
- PASS 또는 FAIL 판정
- 최근 10건 기록 표시
- 로그 CSV 저장
- 포터블 배포 실행 지원

## 3. 현재 동작 흐름

핵심 로직은 [`MeasurementRecorder`](src/current_daemon/service.py:27) 에 모여 있습니다.

현재 측정 흐름은 다음과 같습니다.

1. QR 입력 요청이 [`POST /api/measurements`](src/current_daemon/web_api.py:83) 로 들어옵니다.
2. [`MeasurementRecorder.measure_and_log()`](src/current_daemon/service.py:55) 가 호출됩니다.
3. [`_wait_for_download_trigger()`](src/current_daemon/service.py:94) 에서 원시값 `100` 이상을 **3회 연속** 감지할 때까지 폴링합니다.
4. SigmaStudio 다운로드를 실행합니다.
5. `8초` 대기합니다.
6. 최종 전류를 다시 읽습니다.
7. PASS 또는 FAIL 을 판정합니다.
8. [`logs/current_measurement_log.csv`](logs/current_measurement_log.csv) 에 저장합니다.

## 4. PASS 또는 FAIL 기준

판정 로직은 [`MeasurementThreshold`](src/current_daemon/domain.py:48) 에 정의되어 있습니다.

- PASS 조건: 원시값 `10 <= current <= 2000`
- FAIL 조건: 위 범위를 벗어나는 경우

표시값은 원시값을 100으로 나누어 `mA` 형식으로 표시합니다.

- 원시값 `10` → `0.10mA`
- 원시값 `2000` → `20.00mA`

## 5. 실행 방법

### 5.1 개발 환경 실행

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

### 5.2 포터블 배포 실행

포터블 배포본은 [`../Current_Mes_SW/run.bat`](../Current_Mes_SW/run.bat) 기준으로 실행합니다.

```bat
run.bat
```

이 스크립트는 내장된 포터블 Python 런타임으로 [`../Current_Mes_SW/app.py`](../Current_Mes_SW/app.py) 를 실행합니다.

## 6. 주요 파일 구조

### 실행 진입점

- [`app.py`](app.py): 웹 서버 실행 진입점

### 백엔드 핵심 모듈

- [`src/current_daemon/config.py`](src/current_daemon/config.py): 운영 설정
- [`src/current_daemon/service.py`](src/current_daemon/service.py): 측정 흐름, 트리거 감지, SigmaStudio 다운로드, 최종 저장
- [`src/current_daemon/serial_reader.py`](src/current_daemon/serial_reader.py): 계측기 시리얼 통신 및 COM 상태 확인
- [`src/current_daemon/web_api.py`](src/current_daemon/web_api.py): FastAPI 라우트 및 정적 자산 응답
- [`src/current_daemon/status_service.py`](src/current_daemon/status_service.py): 최근 측정, COM 상태, 다운로드 상태 관리
- [`src/current_daemon/logger.py`](src/current_daemon/logger.py): CSV 로깅
- [`src/current_daemon/sigma_studio.py`](src/current_daemon/sigma_studio.py): SigmaStudio 연동 래퍼

### 프런트엔드

- [`web/index.html`](web/index.html): 메인 대시보드 화면
- [`web/app.js`](web/app.js): UI 상태 갱신 및 API 호출
- [`web/styles.css`](web/styles.css): 스타일 정의
- [`web/assets/logo.png`](web/assets/logo.png): 브랜드 로고

### SigmaStudio Fallback

- [`SigmaDownloader.cs`](SigmaDownloader.cs): C# 콘솔 앱 소스
- [`SigmaDownloader.exe`](SigmaDownloader.exe): Fallback 실행 파일

### 로그

- [`logs/current_measurement_log.csv`](logs/current_measurement_log.csv): 측정 로그
- [`logs/sigma_manual_test.txt`](logs/sigma_manual_test.txt): 수동 SigmaStudio 테스트 로그
- [`logs/sigma_fallback_test.txt`](logs/sigma_fallback_test.txt): Fallback 테스트 로그

## 7. 설정 위치

운영 설정은 [`build_config()`](src/current_daemon/config.py:42) 에서 조정합니다.

주요 항목:

- [`serial_settings.port`](src/current_daemon/config.py:13): COM 포트 고정값, 없으면 자동 감지
- [`web_host`](src/current_daemon/config.py:24)
- [`web_port`](src/current_daemon/config.py:25)
- [`pass_min_raw_value`](src/current_daemon/config.py:26)
- [`pass_max_raw_value`](src/current_daemon/config.py:27)
- [`download_trigger_raw_value`](src/current_daemon/config.py:28)
- [`download_trigger_confirm_count`](src/current_daemon/config.py:29)
- [`trigger_poll_interval_seconds`](src/current_daemon/config.py:30)
- [`input_refocus_delay_seconds`](src/current_daemon/config.py:32)
- [`measurement_delay_seconds`](src/current_daemon/config.py:33)
- [`sigma_studio_dll_path`](src/current_daemon/config.py:36)
- [`sigma_downloader_executable_path`](src/current_daemon/config.py:37)

## 8. COM 포트 동작

COM 포트 감지는 [`WatanabeA7212Reader`](src/current_daemon/serial_reader.py:23) 에서 처리합니다.

- 설정에 포트가 지정되면 해당 포트를 사용합니다.
- 지정되지 않으면 [`comports()`](src/current_daemon/serial_reader.py:8) 목록에서 첫 번째 포트를 사용합니다.
- UI 상태 배지에는 `COM4 CONNECTED` 같은 형식으로 실제 포트명이 표시됩니다.

## 9. SigmaStudio 연동

SigmaStudio 연동은 2가지 경로를 지원합니다.

### 9.1 Pythonnet 직접 호출

- [`src/current_daemon/sigma_studio.py`](src/current_daemon/sigma_studio.py)
- [`pythonnet`](requirements.txt) 을 사용합니다.
- [`Analog.SigmaStudioServer.dll`](src/current_daemon/config.py:86) 을 로드한 뒤 [`COMPILE_PROJECT()`](src/current_daemon/sigma_studio.py:58) 호출을 시도합니다.

### 9.2 Fallback C# CLI

- [`SigmaDownloader.exe`](SigmaDownloader.exe)
- Pythonnet 사용이 실패하거나 비트 충돌이 발생하면 fallback CLI를 실행합니다.

## 10. 웹 UI 동작

브라우저 UI는 다음 정보를 제공합니다.

- 현재 시리얼
- 현재 전류값
- PASS 또는 FAIL 상태
- COM 연결 상태
- SigmaStudio 다운로드 상태
- 최근 10건 측정 기록

또한 앱 실행 시 [`app.py`](app.py) 가 브라우저를 자동으로 엽니다.

## 11. 테스트

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

## 12. 운영 팁

- SigmaStudio는 동일 PC에서 실행 중이어야 합니다.
- 포터블 배포 환경에서는 Windows 명령 출력 인코딩 차이로 문제가 생길 수 있으므로, 배포본 [`run.bat`](../Current_Mes_SW/run.bat) 과 포터블 [`app.py`](../Current_Mes_SW/app.py) 는 최신 버전으로 유지해야 합니다.
- Edge 캐시 문제를 줄이기 위해 실행 시 브라우저는 timestamp 쿼리스트링을 붙여 자동 오픈됩니다.

## 13. 참고 자료

- UI 참고 시안: [`design/screen.png`](design/screen.png)
- 디자인 시스템: [`design/DESIGN.md`](design/DESIGN.md)
- 초기 레이아웃 참고: [`design/code.html`](design/code.html)
