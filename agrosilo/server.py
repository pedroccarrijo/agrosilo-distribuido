"""Servidor TCP concorrente do AgroSilo."""
import argparse
import logging
import math
import os
import socketserver
import sqlite3

from .protocol import ProtocolError, receive_message, send_message
from .replication import Primary, Secondary, initialize_role
from .service import AgroSilo, RequestError
from .storage import Storage

LOG = logging.getLogger(__name__)


def error(code, message):
    return {"ok": False, "erro": {"codigo": code, "mensagem": message}}


class RequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        timeout = self.server.request_timeout
        try:
            request = receive_message(self.request, timeout)
            if request is None:
                return
            result = self.server.service.execute(request)
            response = {"ok": True, "dados": result}
            LOG.info("%s %s", self.client_address, request["operacao"])
        except RequestError as exc:
            response = error(exc.code, str(exc))
        except ProtocolError as exc:
            response = error("MENSAGEM_INVALIDA", str(exc))
        except TimeoutError:
            response = error("TIMEOUT", "Prazo para receber a requisição esgotado.")
        except OSError as exc:
            LOG.info("%s desconectado: %s", self.client_address, exc)
            return
        except sqlite3.Error:
            LOG.exception("Erro ao acessar o banco")
            response = error("ERRO_INTERNO", "Banco temporariamente indisponível.")

        try:
            send_message(self.request, response, timeout)
        except (OSError, ProtocolError) as exc:
            LOG.info("%s resposta não enviada: %s", self.client_address, exc)


class AgroSiloServer(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self, address, service, timeout):
        self.service = service
        self.request_timeout = timeout
        super().__init__(address, RequestHandler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--role", choices=["standalone", "primary", "secondary"],
                        default="standalone")
    parser.add_argument("--replica-host", default="127.0.0.1")
    parser.add_argument("--replica-port", type=int, default=9001)
    parser.add_argument("--replica-timeout", type=float, default=1)
    parser.add_argument("--db")
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--max-temperatura", type=float, default=30,
                        help="Limite superior demonstrativo em °C")
    parser.add_argument("--max-umidade", type=float, default=65,
                        help="Limite superior demonstrativo em %%")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 300:
        parser.error("--timeout deve estar no intervalo (0, 300] segundos.")
    if args.port is None:
        args.port = 9001 if args.role == "secondary" else 9000
    if args.db is None:
        args.db = "data/agrosilo.sqlite3" if args.role == "standalone" else f"data/{args.role}.sqlite3"
    key = os.environ.get("AGROSILO_REPLICATION_KEY", "")
    if args.role != "standalone" and not (0 < len(key) <= 128 and key.isascii()):
        parser.error("Defina AGROSILO_REPLICATION_KEY com 1 a 128 caracteres ASCII.")
    if not 0 < args.replica_timeout <= 300 or not 1 <= args.replica_port <= 65535:
        parser.error("Porta ou prazo da réplica inválido.")
    if not 0 <= args.port <= 65535:
        parser.error("--port deve estar entre 0 e 65535.")

    if args.role == "primary" and args.port == args.replica_port:
        parser.error("Use portas diferentes para o primário e o secundário.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        service = AgroSilo(Storage(args.db), args.max_temperatura, args.max_umidade)
        initialize_role(service.storage, args.role)
        if args.role == "primary":
            service = Primary(service, args.replica_host, args.replica_port, args.replica_timeout, key)
        elif args.role == "secondary":
            service = Secondary(service, key)
        with AgroSiloServer((args.host, args.port), service, args.timeout) as server:
            print(f"AgroSilo ouvindo em {server.server_address[0]}:{server.server_address[1]}",
                  flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Servidor encerrado.")
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(1, f"Falha ao iniciar o servidor: {exc}\n")


if __name__ == "__main__":
    main()
