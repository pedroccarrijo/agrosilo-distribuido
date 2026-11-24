"""Uma mensagem JSON UTF-8 por linha, sobre TCP."""
import json
import time

MAX_FRAME = 16_384


class ProtocolError(ValueError):
    pass


class IncompleteFrame(ProtocolError):
    """O socket fechou antes de receber o delimitador."""


def reject_constant(value):
    raise ValueError(f"Constante JSON inválida: {value}")


def receive_message(sock, timeout):
    deadline = time.monotonic() + timeout
    frame = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Prazo para receber a mensagem esgotado.")
        sock.settimeout(remaining)
        chunk = sock.recv(min(4096, MAX_FRAME + 1 - len(frame)))
        if not chunk:
            if not frame:
                return None
            raise IncompleteFrame("Conexão encerrada antes do delimitador.")
        end = chunk.find(b"\n")
        if end >= 0:
            frame.extend(chunk[:end])
            break
        frame.extend(chunk)
        if len(frame) > MAX_FRAME:
            raise ProtocolError("Mensagem excede 16384 bytes.")

    try:
        message = json.loads(frame.decode("utf-8"), parse_constant=reject_constant)
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("JSON UTF-8 inválido.") from exc
    if not isinstance(message, dict):
        raise ProtocolError("A mensagem deve ser um objeto JSON.")
    return message


def send_message(sock, message, timeout):
    frame = json.dumps(message, ensure_ascii=True, allow_nan=False).encode("utf-8")
    if len(frame) > MAX_FRAME:
        raise ProtocolError("Mensagem excede 16384 bytes.")
    sock.settimeout(timeout)
    sock.sendall(frame + b"\n")
