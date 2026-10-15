/*
 * This file is part of OpenTTD.
 * OpenTTD is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 2.
 * OpenTTD is distributed in the hope that it is useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See the GNU General Public License for more details. You should have received a copy of the GNU General Public License along with OpenTTD. If not, see <https://www.gnu.org/licenses/old-licenses/gpl-2.0>.
 */

/** @file unix_main.cpp Main entry for Unix. */

#include "../../stdafx.h"
#include "../../openttd.h"
#include "../../crashlog.h"
#include "../../core/random_func.hpp"
#include "../../string_func.h"
#include "../../thread.h"

#include <time.h>
#include <signal.h>
#include <stdlib.h>

#if defined(__OHOS__)
	#include <SDL.h>
#elif defined(__ANDROID__)
	#define main SDL_main
	extern "C" int CDECL main(int, char *[]);
#endif

#include "../../safeguards.h"

#if defined(__OHOS__) || defined(__ANDROID__)
extern "C" void ohos_probe(const char *msg);
#endif

int CDECL main(int argc, char *argv[])
{
#ifdef __OHOS__
	/* HarmonyOS app processes have no HOME set; without it OpenTTD cannot
	 * find its personal (save/settings) directory. SDL3's OHOS backend
	 * returns the app files dir, which build-ohos.sh pairs with
	 * PERSONAL_DIR=openttd, matching the rawfile install path. */
	if (getenv("HOME") == nullptr) {
		char *pref = SDL_GetPrefPath(".", ".");
		if (pref != nullptr) setenv("HOME", pref, 0);
	}
	#if defined(__OHOS__) || defined(__ANDROID__)
	{
		const char *h = getenv("HOME");
		if (h != nullptr) { std::string s = "__HOME__ "; s += h; ohos_probe(s.c_str()); }
	}
	#endif
#endif

	/* Make sure our arguments contain only valid UTF-8 characters. */
	for (int i = 0; i < argc; i++) StrMakeValidInPlace(argv[i]);

	PerThreadSetupInit();
	CrashLog::InitialiseCrashLog();
	CrashLog::InitialiseExceptionTerminateHandler();

	InitialiseRandomSeeds();

	signal(SIGPIPE, SIG_IGN);

	return openttd_main(std::span(argv, argc));
}

#if defined(__OHOS__) || defined(__ANDROID__)
/* Temporary startup probes for emulator bring-up. SDL_Log is the one channel
 * that reaches hilog on OHOS (the SDL3 port logs through it, domain A00000),
 * so milestones are visible via `hdc shell hilog -x`. */
#include <stdio.h>
#include <time.h>
#if defined(__ANDROID__)
#include <android/log.h>
#endif
extern "C" void ohos_probe(const char *msg)
{
#if defined(__ANDROID__)
	__android_log_print(ANDROID_LOG_INFO, "ottd", "[ottd probe] %s", msg);
#else
	SDL_Log("[ottd probe] %s", msg);
#endif
#if defined(__ANDROID__)
	const char *paths[] = { "ottd.probe" };
#else
	const char *paths[] = { "/data/local/tmp/ottd.probe", "/data/storage/el1/base/files/ottd.probe" };
#endif
	for (const char *p : paths) {
		FILE *f = fopen(p, "a");
		if (f != nullptr) {
			fprintf(f, "%lld %s\n", (long long)time(nullptr), msg);
			fclose(f);
			break;
		}
	}
}

/* SDL3's OpenHarmony launcher (sdlLaunchMain) dlsym()s the entry symbol and
 * calls it with no arguments from a separate thread, so provide a wrapper.
 * argv[0] must be writable: main() sanitizes the arguments in place. */
extern "C" int CDECL ottd_ohos_main()
{
	char progname[] = "openttd";
	char *argv[1] = { progname };
	ohos_probe("ottd_ohos_main");
	return main(1, argv);
}
#endif
