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

#ifdef __OHOS__
/* SDL3's OpenHarmony launcher (sdlLaunchMain) dlsym()s the entry symbol and
 * calls it with no arguments from a separate thread, so provide a wrapper. */
extern "C" int CDECL ottd_ohos_main()
{
	char *argv[1] = { const_cast<char *>("openttd") };
	return main(1, argv);
}
#endif
