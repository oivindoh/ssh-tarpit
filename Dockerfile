FROM debian:12-slim AS build
RUN apt-get update && \
    apt-get install --no-install-suggests --no-install-recommends --yes python3 python3-venv curl ca-certificates && \
    python3 -m venv /venv && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv && \
    rm -rf /root/.local

FROM build AS build-venv
COPY requirements.txt /requirements.txt
COPY . /src
RUN . /venv/bin/activate && uv pip install --disable-pip-version-check -r /requirements.txt && \
    uv pip install /src

FROM gcr.io/distroless/python3-debian12
COPY --from=build-venv /venv /venv
ENV PYTHONUNBUFFERED=1
WORKDIR /
EXPOSE 2222/tcp
EXPOSE 8000/tcp
ENTRYPOINT [ "/venv/bin/ssh-tarpit", "-a", "0.0.0.0" ]
