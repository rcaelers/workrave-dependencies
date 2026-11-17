"""Exercise the installed Python transport and code generator packages."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile

import grpc
from grpc_tools import protoc


with tempfile.TemporaryDirectory(prefix="wr-grpc-") as directory:
    root = Path(directory)
    address = "unix:" + (root / "rpc.sock").as_posix()
    with ThreadPoolExecutor(max_workers=1) as executor:
        server = grpc.server(executor)
        server.add_generic_rpc_handlers(
            (grpc.method_handlers_generic_handler(
                "smoke.Echo",
                {"Ping": grpc.unary_unary_rpc_method_handler(lambda request, context: request)},
            ),)
        )
        if not server.add_insecure_port(address):
            raise RuntimeError("Python gRPC could not bind its Unix socket")
        server.start()
        try:
            with grpc.insecure_channel(address) as channel:
                grpc.channel_ready_future(channel).result(timeout=10)
                response = channel.unary_unary("/smoke.Echo/Ping")(b"AF_UNIX", timeout=10)
                if response != b"AF_UNIX":
                    raise RuntimeError("Python gRPC Unix socket RPC returned the wrong response")
        finally:
            server.stop(0).wait()

    proto = root / "smoke.proto"
    proto.write_text('syntax = "proto3"; message Ping { string value = 1; }\n')
    result = protoc.main([
        "grpc_tools.protoc", f"-I{root}", f"--python_out={root}",
        f"--grpc_python_out={root}", str(proto),
    ])
    if result != 0 or not all((root / name).is_file() for name in ("smoke_pb2.py", "smoke_pb2_grpc.py")):
        raise RuntimeError("Python gRPC code generation failed")

print("Python gRPC AF_UNIX RPC and code generation succeeded")
