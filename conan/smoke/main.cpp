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
  window.resize(320, 200);
  window.show();
  return application.exec();
}

#include "main.moc"
