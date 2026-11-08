// Run on Windows to verify the linked gRPC binary, not just its capability marker.
#include <chrono>
#include <filesystem>
#include <iostream>
#include <grpcpp/generic/async_generic_service.h>
#include <grpcpp/grpcpp.h>

int main()
{
  const auto unique = std::chrono::steady_clock::now().time_since_epoch().count();
  const auto path = std::filesystem::temp_directory_path() / ("wr-" + std::to_string(unique) + ".sock");
  const auto address = "unix:" + path.generic_string();
  std::error_code ignored;
  std::filesystem::remove(path, ignored);

  grpc::AsyncGenericService service;
  grpc::ServerBuilder builder;
  builder.RegisterAsyncGenericService(&service);
  auto queue = builder.AddCompletionQueue();
  builder.AddListeningPort(address, grpc::InsecureServerCredentials());
  auto server = builder.BuildAndStart();
  bool connected = false;
  if (server)
    {
      auto channel = grpc::CreateChannel(address, grpc::InsecureChannelCredentials());
      connected = channel->WaitForConnected(std::chrono::system_clock::now() + std::chrono::seconds(5));
      server->Shutdown();
    }
  queue->Shutdown();
  void *tag = nullptr;
  bool ok = false;
  while (queue->Next(&tag, &ok)) {}
  server.reset();
  std::filesystem::remove(path, ignored);
  if (!connected)
    std::cerr << "gRPC could not connect to its Windows Unix-domain-socket listener\n";
  else
    std::cout << "gRPC AF_UNIX connection succeeded\n";
  return connected ? 0 : 1;
}
