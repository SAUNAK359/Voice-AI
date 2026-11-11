# CPU reference image only. For GPU, install CUDA 12/cuDNN9 or use an NVIDIA base image.
FROM python:3.12-slim
WORKDIR /srv/rizzler
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[voice]" && useradd -m -u 10001 rizzler
USER rizzler
ENV RIZZLER_HOST=0.0.0.0 RIZZLER_PORT=8000
EXPOSE 8000
CMD ["python", "-m", "rizzler"]
