# CMI Modbus-Output IST-Konfiguration

Quelle: `http://192.168.178.45/settings_output-M.cgi` — read-only ausgelesen.

## Analog (M1..M16) — Holding-Register

| Slot | Bezeichnung | Source | Adr | FC | DType | Faktor | actval |
|------|------------|--------|----|----|-------|--------|--------|
| M1 | AI_T_Aussen | C1 | 0 | FC16 multi regs | i16 | 10.00000 | 1100 |
| M2 | AI_T_Puffer_o | C2 | 1 | FC16 multi regs | i16 | 10.00000 | 2400 |
| M3 | AI_T_Heizkr_RL | C3 | 2 | FC16 multi regs | i16 | 10.00000 | 2770 |
| M4 | AI_T_WW_Speich | C4 | 3 | FC16 multi regs | i16 | 10.00000 | 5000 |
| M5 | AI_NW_Stat_21 | C5 | 4 | FC16 multi regs | i16 | 10.00000 | 0 |
| M6 | AI_Traum_SOLL | C6 | 5 | FC16 multi regs | i16 | 10.00000 | 2300 |
| M7 | AI_T_Heissgas | C7 | 6 | FC16 multi regs | i16 | 10.00000 | 3720 |
| M8 | AI_T_Fluessig | C8 | 7 | FC16 multi regs | i16 | 10.00000 | 3520 |
| M9 | AI_T_Saugltg | C9 | 8 | FC16 multi regs | i16 | 10.00000 | 1430 |
| M10 | AI_BetrStd_Verd | C10 | 9 | FC16 multi regs | u32 | 1.00000 | 13966 |
| M11 | AI_Schaltz_Verd | C11 | 10 | FC16 multi regs | u32 | 1.00000 | 24759 |
| M12 | AI_FBH_PumpStatus | C12 | 11 | FC16 multi regs | i16 | 1.00000 | 0 |
| M13 |  | None | 0 | None | i16 | 1.00000 | 0 |
| M14 | AI_Meld_Heizung | C14 | 13 | FC16 multi regs | i16 | 1.00000 | 0 |
| M15 | AI_Meld_WW | C15 | 14 | FC16 multi regs | i16 | 1.00000 | 0 |
| M16 | AI_VL_Solltemp | C16 | 15 | FC16 multi regs | i16 | 10.00000 | 2650 |

## Digital (M-1..M-16) — Coils

| Slot | Bezeichnung | Source | Adr | FC | actval |
|------|------------|--------|----|----|--------|
| M-1 | DI_Phasenwaecht | C-1 | 0 | FC05 single coil | ON |
| M-2 | DI_I_Verdichter | C-2 | 1 | FC05 single coil | ON |
| M-3 | DI_ND_Schalter1 | C-3 | 2 | FC05 single coil | ON |
| M-4 | DI_HD_Schalter | C-4 | 3 | FC05 single coil | ON |
| M-5 | DI_ND_Schalter2 | C-5 | 4 | FC05 single coil | ON |
| M-6 | DI_Meld_Heizung | C-6 | 5 | FC05 single coil | OFF |
| M-7 | DI_Pumpe_Hzkr | C-7 | 6 | FC05 single coil | ON |
| M-8 | DI_Ladepumpe | C-8 | 7 | FC05 single coil | OFF |
| M-9 | DI_Verdichter | C-9 | 8 | FC05 single coil | OFF |
| M-10 | DI_Alarm_Ext | C-10 | 9 | FC05 single coil | OFF |
| M-11 | DI_MVR0407_FL1 | C-11 | 10 | FC05 single coil | OFF |
| M-12 | DI_MVR0407_Nach2 | C-12 | 11 | FC05 single coil | OFF |
| M-13 | DI_Ventil_WW | C-13 | 12 | FC05 single coil | OFF |
| M-14 | DI_Heizstab_HZ | C-14 | 13 | FC05 single coil | OFF |
| M-15 | DI_Heizstab_WW | C-15 | 14 | FC05 single coil | OFF |
| M-16 | DI_Pumpe_Zirku | C-16 | 15 | FC05 single coil | OFF |
