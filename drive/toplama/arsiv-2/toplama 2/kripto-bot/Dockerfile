FROM python:3.11-slim

# Ortam güvenliği: bytecode yazma ve tamponsuz güvenli çıktı
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Yetkileri kısıtlanmış özel kullanıcı (appuser) oluştur (Non-Root Security)
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 2) Çalışma dizini sahipliğini appuser'a devret ve hassas izinleri kısıtla
RUN chown -R appuser:appuser /app && chmod -R 750 /app

# 3) Root yerine kısıtlı appuser ile çalıştır
USER appuser

EXPOSE 8501

CMD ["python", "-m", "src.main"]
