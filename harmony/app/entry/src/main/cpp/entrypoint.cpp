/*
 * Placeholder native module. The game itself lives in libopenttd.so and is
 * launched from Index.ets via SDL3's sdlLaunchMain("libopenttd.so",
 * "ottd_ohos_main"). This file only keeps the DevEco C++ module building.
 */
extern "C" __attribute__((visibility("default"))) int ottd_entry_placeholder()
{
    return 0;
}
