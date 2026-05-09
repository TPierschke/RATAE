# CMI Modbus-Output IST-Konfiguration

Quelle: `http://192.168.178.45/settings_output-M.cgi` — read-only ausgelesen.

## Analog (M1..M16) — Holding-Register

| Slot | Bezeichnung | Source | Adr | FC | DType | Faktor | actval |
|------|------------|--------|----|----|-------|--------|--------|
| M1 | Aussentemp | C1 | 0 | FC16 multi regs | i16 | 10.00000 | 1030 |
| M2 | Vorlauf | C2 | 1 | FC16 multi regs | i16 | 10.00000 | 2920 |
| M3 | Ruecklauf | C3 | 2 | FC16 multi regs | i16 | 10.00000 | 2980 |
| M4 | Warmwasser | C4 | 3 | FC16 multi regs | i16 | 10.00000 | 5000 |
| M5 |  | None | 0 | None | i16 | 1.00000 | 0 |
| M6 | TRaum1 | C6 | 5 | FC16 multi regs | i16 | 10.00000 | 0 |
| M7 | Heissgas | C7 | 6 | FC16 multi regs | i16 | 10.00000 | 3780 |
| M8 | Fluessigkeit | C8 | 7 | FC16 multi regs | i16 | 10.00000 | 3560 |
| M9 | Saugleitung | C9 | 8 | FC16 multi regs | i16 | 10.00000 | 1640 |
| M10 | BetrStdVerdichter | C10 | 9 | FC16 multi regs | u32 | 1.00000 | 13944 |
| M11 | SchaltungenVerdichter | C11 | 10 | FC16 multi regs | u32 | 1.00000 | 24718 |
| M12 | BetrStdHeizstabFB | C12 | 11 | FC16 multi regs | u32 | 1.00000 | 0 |
| M13 | BetrStdHeizstabWW | C13 | 12 | FC16 multi regs | u32 | 1.00000 | 1646 |
| M14 | MessageFB | C14 | 13 | FC16 multi regs | u16 | 1.00000 | 0 |
| M15 | MessageWW | C15 | 14 | FC16 multi regs | u16 | 1.00000 | 0 |
| M16 | VorlaufSoll | C16 | 15 | FC16 multi regs | i16 | 10.00000 | 500 |

## Digital (M-1..M-16) — Coils

| Slot | Bezeichnung | Source | Adr | FC | actval |
|------|------------|--------|----|----|--------|
| M-1 | Phasenwaecht | C-1 | 0 | FC05 single coil | ON |
| M-2 | I_Verdichter | C-2 | 1 | FC05 single coil | ON |
| M-3 | ND_Schalter1 | C-3 | 2 | FC05 single coil | ON |
| M-4 | HD_Schalter | C-4 | 3 | FC05 single coil | ON |
| M-5 | ND_Schalter2 | C-5 | 4 | FC05 single coil | ON |
| M-6 | PumpeHzkr | C-6 | 5 | FC05 single coil | OFF |
| M-7 | Ladepumpe | C-7 | 6 | FC05 single coil | OFF |
| M-8 | O_Verdichter | C-8 | 7 | FC05 single coil | OFF |
| M-9 | MVR0407FL1 | C-9 | 8 | FC05 single coil | OFF |
| M-10 | AlarmExt | C-10 | 9 | FC05 single coil | OFF |
| M-11 | MVR0407Nach2 | C-11 | 10 | FC05 single coil | OFF |
| M-12 | VentilWW | C-12 | 11 | FC05 single coil | OFF |
| M-13 | HeizstabWW | C-13 | 12 | FC05 single coil | OFF |
| M-14 | HeizstabHZ | C-14 | 13 | FC05 single coil | OFF |
| M-15 | ZirkPumpe | C-15 | 14 | FC05 single coil | OFF |
| M-16 | ALERT_FB | C-16 | 15 | FC05 single coil | OFF (timeout!) |
