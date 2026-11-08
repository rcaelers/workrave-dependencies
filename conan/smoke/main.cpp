#include <QApplication>
#include <QQuickWidget>
#include <QSvgRenderer>
#include <boost/program_options.hpp>
#include <boost/archive/text_oarchive.hpp>
#include <boost/date_time/posix_time/posix_time.hpp>
#include <fmt/format.h>
#include <spdlog/spdlog.h>
#include <openssl/crypto.h>
#include <sqlite3.h>
#include <sstream>
#ifdef WORKRAVE_SMOKE_GRPC
#include <chrono>
#include <grpcpp/grpcpp.h>
#include "probe.grpc.pb.h"

class ProbeService final : public workrave::dependencies::DependencyProbe::Service
{
  grpc::Status Echo(grpc::ServerContext *, const workrave::dependencies::Probe *request,
                    workrave::dependencies::Probe *response) override
  {
    response->set_text(request->text());
    return grpc::Status::OK;
  }
};

bool check_rpc()
{
  ProbeService service;
  grpc::ServerBuilder builder;
  int port = 0;
  builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(), &port);
  builder.RegisterService(&service);
  auto server = builder.BuildAndStart();
  if (!server || port == 0)
    return false;
  auto stub = workrave::dependencies::DependencyProbe::NewStub(
    grpc::CreateChannel("127.0.0.1:" + std::to_string(port), grpc::InsecureChannelCredentials()));
  grpc::ClientContext context;
  context.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
  workrave::dependencies::Probe request, response;
  request.set_text("Workrave SDK probe");
  const auto status = stub->Echo(&context, request, &response);
  server->Shutdown(std::chrono::system_clock::now() + std::chrono::seconds(5));
  server->Wait();
  return status.ok() && response.text() == request.text();
}
#endif
#ifdef WORKRAVE_SMOKE_DBUS
#include <QDBusMessage>
#endif

class SmokeWidget : public QQuickWidget
{
  Q_OBJECT
public:
  SmokeWidget() { setSource(QUrl("qrc:/Main.qml")); }
};

int main(int argc, char **argv)
{
  QApplication application(argc, argv);
  boost::program_options::options_description options("Smoke test");
  options.add_options()("version", "Dependency versions");
  std::ostringstream text;
  boost::archive::text_oarchive archive(text);
  int year = boost::posix_time::second_clock::universal_time().date().year();
  archive << year;
  spdlog::info("{}", fmt::format("Qt {}, OpenSSL {}, SQLite {}", qVersion(),
                               OpenSSL_version(OPENSSL_VERSION), sqlite3_libversion()));
  SmokeWidget window;
#ifdef WORKRAVE_SMOKE_DBUS
  const auto message = QDBusMessage::createSignal("/org/workrave/Probe", "org.workrave.Probe", "Ready");
  if (message.type() != QDBusMessage::SignalMessage)
    return 3;
#endif
  if (application.arguments().contains("--self-test")) {
    application.processEvents();
#ifdef WORKRAVE_SMOKE_GRPC
    if (!check_rpc())
      return 4;
#endif
    return window.status() == QQuickWidget::Ready ? 0 : 2;
  }
  window.resize(320, 200);
  window.show();
  return application.exec();
}

#include "main.moc"
