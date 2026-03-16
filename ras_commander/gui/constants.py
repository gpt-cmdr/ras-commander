"""
GUI automation constants for HEC-RAS and RASMapper.

VB6 Thunder class names, Win32 message constants, and known menu IDs
derived from binary analysis of HEC-RAS 6.6 (RASDecomp project).
"""


class VB6ClassNames:
    """VB6 runtime window class names (from HEC-RAS 6.6 binary analysis)."""

    MDI_FORM = "ThunderRT6MDIForm"
    FORM_DC = "ThunderRT6FormDC"
    FORM = "ThunderRT6Form"
    COMMAND_BUTTON = "ThunderRT6CommandButton"
    TEXT_BOX = "ThunderRT6TextBox"
    COMBO_BOX = "ThunderRT6ComboBox"
    CHECK_BOX = "ThunderRT6CheckBox"
    OPTION_BUTTON = "ThunderRT6OptionButton"
    LIST_BOX = "ThunderRT6ListBox"
    PICTURE_BOX = "ThunderRT6PictureBoxDC"
    FRAME = "ThunderRT6Frame"
    LABEL = "ThunderRT6Label"


class Win32Constants:
    """Win32 message and style constants used by GUI automation."""

    # Window messages
    WM_COMMAND = 0x0111
    WM_CLOSE = 0x0010
    WM_NULL = 0x0000

    # Menu flags
    MF_BYPOSITION = 0x00000400

    # Button messages
    BM_CLICK = 0x00F5

    # ComboBox messages
    CB_GETCOUNT = 0x0146
    CB_GETLBTEXT = 0x0148
    CB_GETLBTEXTLEN = 0x0149
    CB_SETCURSEL = 0x014E

    # SendMessageTimeout flags
    SMTO_ABORTIFHUNG = 0x0002

    # Keyboard event flags
    KEYEVENTF_KEYUP = 0x0002

    # Virtual key codes
    VK_RETURN = 0x0D
    VK_MENU = 0x12  # Alt key

    # Standard dialog class
    DIALOG_CLASS = "#32770"
    POPUP_MENU_CLASS = "#32768"
