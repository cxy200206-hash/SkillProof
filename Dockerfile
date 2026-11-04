FROM python:3.13-slim
WORKDIR /app
COPY . .
ENV PORT=8000
EXPOSE 8000
CMD ["python", "app.py"]
