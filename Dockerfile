# =======================
# 1) Build stage
# =======================
FROM python:3.11-slim AS builder

# 시스템 필수 패키지 (필요 시 추가)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성만 먼저 복사하여 Docker 캐시 활용
COPY requirements.txt .

# 패키지들을 전역 사용자 공간에 설치 (멀티 스테이지에서 권장되는 패턴)
RUN pip install --user --no-cache-dir -r requirements.txt

# =======================
# 2) Runtime stage
# =======================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# uvicorn이 내부에서 0.0.0.0:8000으로 뜬다고 가정
EXPOSE 8000

WORKDIR /app

# builder 단계에서 설치한 패키지 복사
# /root/.local/ 이 --user 설치 기본 경로
COPY --from=builder /root/.local /root/.local

# PATH에 user base bin 추가
ENV PATH=/root/.local/bin:${PATH}

# 앱 소스 복사
COPY . .

# uvicorn으로 FastAPI 실행
# app/main.py 안에 "app = FastAPI()" 가 있다고 가정
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]