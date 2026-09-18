cmake_minimum_required(VERSION 3.20)
project(stukachDrawOverride LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Maya version — change for different Maya releases
set(MAYA_VERSION 2025 CACHE STRING "Maya version number")

# Find Maya SDK
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
find_package(Maya REQUIRED)

# Sources
file(GLOB SOURCE_FILES "src/*.cpp" "src/*.h")

# Build as Maya plugin (.mll on Windows)
add_library(${PROJECT_NAME} SHARED ${SOURCE_FILES})
target_include_directories(${PROJECT_NAME} PRIVATE ${MAYA_INCLUDE_DIR})
target_link_libraries(${PROJECT_NAME} PRIVATE ${MAYA_LIBRARIES})

# Maya plugin setup (extension, exports, defines)
MAYA_PLUGIN(${PROJECT_NAME})
