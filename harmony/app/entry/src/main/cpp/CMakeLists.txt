# The game (libopenttd.so), SDL3 with the OpenHarmony backend and sdl2-compat
# are cross-compiled by harmony/build-ohos.sh and placed into entry/libs/<abi>/.
# This module only builds a placeholder library.
cmake_minimum_required(VERSION 3.16)
project(jgrpp_entry)

add_library(entry SHARED entrypoint.cpp)
target_link_libraries(entry PUBLIC libace_napi.z.so)
