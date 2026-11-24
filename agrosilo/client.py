"""Cliente de terminal e função reutilizável para o protocolo AgroSilo."""
import argparse
import json
import random
import socket
import sys

from .protocol import IncompleteFrame, ProtocolError, receive_message, send_message


READ_OPERATIONS = {"consultar_silo", "listar_silos", "consultar_medicoes"}


class NoResponse(ProtocolError):
    """O servidor encerrou a conexão antes de enviar uma resposta."""


def request(host, port, operation, data=None, timeout=5):
    with socket.create_connection((host, port), timeout=timeout) as connection:
        send_message(connection, {"operacao": operation, "dados": data if data is not None else {}},
                     timeout)
        response = receive_message(connection, timeout)
    if response is None:
        raise NoResponse("Servidor encerrou a conexão sem responder.")
    if response.get("ok") is True and isinstance(response.get("dados"), dict):
        return response
    if response.get("ok") is False and isinstance(response.get("erro"), dict):
        return response
    raise ProtocolError("Formato de resposta inesperado.")


def request_with_failover(primary, secondary, operation, data=None, timeout=5):
    """Retorna a resposta pública e o endereço do servidor que respondeu."""
    try:
        return request(*primary, operation, data, timeout), primary
    except (OSError, NoResponse, IncompleteFrame) as primary_error:
        if operation not in READ_OPERATIONS or secondary is None or secondary == primary:
            raise
        try:
            return request(*secondary, operation, data, timeout), secondary
        except (OSError, ProtocolError) as secondary_error:
            raise ConnectionError(
                f"Primário {primary[0]}:{primary[1]}: {primary_error}. "
                f"Secundário {secondary[0]}:{secondary[1]}: {secondary_error}."
            ) from secondary_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--replica-host", help="Host do secundário. Padrão: mesmo host.")
    parser.add_argument("--replica-port", type=int, default=9001)
    parser.add_argument("--sem-failover", action="store_true")
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("cadastrar_silo").add_argument("nome")
    commands.add_parser("consultar_silo").add_argument("silo_id", type=int)
    listing = commands.add_parser("listar_silos")
    listing.add_argument("--limite", type=int)
    listing.add_argument("--apos-id", type=int)
    measurement = commands.add_parser("registrar_medicao")
    measurement.add_argument("silo_id", type=int)
    measurement.add_argument("temperatura", type=float)
    measurement.add_argument("umidade", type=float)
    history = commands.add_parser("consultar_medicoes")
    history.add_argument("silo_id", type=int)
    history.add_argument("--limite", type=int)
    history.add_argument("--antes-id", type=int)
    commands.add_parser("simular").add_argument("silo_id", type=int)
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error("--timeout deve estar no intervalo (0, 300] segundos.")
    if not 1 <= args.port <= 65535 or not 1 <= args.replica_port <= 65535:
        parser.error("As portas devem estar entre 1 e 65535.")

    primary = (args.host, args.port)
    secondary = None if args.sem_failover else (args.replica_host or args.host, args.replica_port)
    data = {key: value for key, value in vars(args).items()
            if key not in {"host", "port", "timeout", "operation", "replica_host",
                           "replica_port", "sem_failover"} and value is not None}
    operation = args.operation
    if operation == "simular":
        operation = "registrar_medicao"
        data.update(temperatura=round(random.uniform(20, 38), 1),
                    umidade=round(random.uniform(45, 85), 1))

    try:
        response, endpoint = request_with_failover(primary, secondary, operation, data, args.timeout)
    except TimeoutError:
        print("Tempo de espera esgotado.", file=sys.stderr)
        return report_transport_failure(operation)
    except (OSError, NoResponse, IncompleteFrame) as exc:
        print(f"Falha de conexão com o servidor: {exc}", file=sys.stderr)
        return report_transport_failure(operation)
    except ProtocolError as exc:
        print(f"Erro de mensagem: {exc}", file=sys.stderr)
        return report_transport_failure(operation)
    except ValueError as exc:
        print(f"Erro de mensagem: {exc}", file=sys.stderr)
        return 1

    if endpoint != primary:
        print(f"Failover de leitura para {endpoint[0]}:{endpoint[1]}.", file=sys.stderr)
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response["ok"] else 1


def report_transport_failure(operation):
    if operation not in READ_OPERATIONS:
        print("Escrita sem confirmação. Consulte o estado antes de repetir.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
