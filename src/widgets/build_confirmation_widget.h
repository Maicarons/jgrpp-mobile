/*
 * This file is part of OpenTTD.
 * OpenTTD is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 2.
 * OpenTTD is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See the GNU General Public License for more details. You should have received a copy of the GNU General Public License along with OpenTTD. If not, see <https://www.gnu.org/licenses/old-licenses/gpl-2.0>.
 */

/** @file build_confirmation_widget.h Types related to the build confirmation widgets. */

#ifndef WIDGETS_BUILD_CONFIRMATION_WIDGET_H
#define WIDGETS_BUILD_CONFIRMATION_WIDGET_H

#include "../widget_type.h"

/** Widgets of the #BuildConfirmationWindow class. */
enum BuildConfirmationWidgets : WidgetID {
	WID_BC_PRICE,  ///< Estimated price.
	WID_BC_OK,     ///< Confirm or cancel action (top half confirms, bottom half cancels).
	WID_BC_CANCEL, ///< Cancel action.
	WID_BC_PANEL,  ///< Background panel.
};

#endif /* WIDGETS_BUILD_CONFIRMATION_WIDGET_H */
