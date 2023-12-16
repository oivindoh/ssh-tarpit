FROM docker.io/python:3.12.0
LABEL upstream="Vladislav Yarmak <vladislav-ex-src@vm-0.com>"

ARG UID=18722
ARG USER=ssh-tarpit
ARG GID=18722

RUN true \
   && addgroup --gid "$GID" "$USER" \
   && adduser \
        --disabled-password \
        --gecos "" \
        --ingroup "$USER" \
        --no-create-home \
        --uid "$UID" \
        "$USER" \
   && true

COPY . /build
WORKDIR /build
RUN pip3 install --no-cache-dir . && pip install -r requirements.txt

USER $USER

EXPOSE 2222/tcp
ENTRYPOINT [ "ssh-tarpit", "-a", "0.0.0.0" ]
