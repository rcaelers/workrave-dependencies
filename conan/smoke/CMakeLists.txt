cmake_minimum_required(VERSION 3.21)
project(workrave_dependencies_smoke LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Svg Xml Quick QuickControls2 QuickWidgets LinguistTools)
find_package(Boost REQUIRED COMPONENTS date_time program_options serialization)
find_package(OpenSSL REQUIRED)
find_package(fmt REQUIRED)
find_package(spdlog REQUIRED)
find_package(SQLite3 REQUIRED)
find_package(GTest REQUIRED)

qt_add_executable(dependencies-smoke WIN32 main.cpp resources.qrc)
target_link_libraries(dependencies-smoke PRIVATE
  Qt6::Core Qt6::Gui Qt6::GuiPrivate Qt6::Widgets Qt6::Svg Qt6::Xml
  Qt6::Quick Qt6::QuickControls2 Qt6::QuickWidgets
  Boost::date_time Boost::program_options Boost::serialization
  OpenSSL::SSL OpenSSL::Crypto fmt::fmt spdlog::spdlog SQLite::SQLite3 GTest::gtest)

# lrelease must be a native Linux executable, just like AUTOMOC/AUTORCC tools.
add_custom_command(OUTPUT translations.qm
  COMMAND Qt::lrelease "${CMAKE_CURRENT_SOURCE_DIR}/translations.ts" -qm translations.qm
  DEPENDS translations.ts)
add_custom_target(translations ALL DEPENDS translations.qm)

install(TARGETS dependencies-smoke RUNTIME DESTINATION bin)
