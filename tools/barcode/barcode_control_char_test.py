from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from datetime import datetime
from pathlib import Path


RS = "\x1e"
GS = "\x1d"
EOT = "\x04"

CONTROL_LABELS = {
    RS: "RS",
    GS: "GS",
    EOT: "EOT",
}

CSV_COLUMNS = [
    "timestamp",
    "source",
    "barcode_raw",
    "barcode_visible",
    "barcode_repr",
    "barcode_utf8_hex",
    "char_codes",
    "contains_rs",
    "contains_gs",
    "contains_eot",
]


def default_barcode() -> str:
    return f"SN123{RS}RS_FIELD{GS}GS_FIELD{EOT}END"


def decode_barcode_argument(value: str) -> str:
    replacements = {
        r"\x1e": RS,
        r"\x1E": RS,
        r"\u001e": RS,
        r"\u001E": RS,
        "<RS>": RS,
        r"\x1d": GS,
        r"\x1D": GS,
        r"\u001d": GS,
        r"\u001D": GS,
        "<GS>": GS,
        r"\x04": EOT,
        r"\x4": EOT,
        r"\u0004": EOT,
        "<EOT>": EOT,
    }

    decoded_value = value
    for token, control_character in replacements.items():
        decoded_value = decoded_value.replace(token, control_character)

    return decoded_value


def visible_barcode(value: str) -> str:
    visible_parts: list[str] = []
    for character in value:
        label = CONTROL_LABELS.get(character)
        if label is not None:
            visible_parts.append(f"<{label}>")
            continue

        codepoint = ord(character)
        if codepoint < 32 or codepoint == 127:
            visible_parts.append(f"<0x{codepoint:02X}>")
            continue

        visible_parts.append(character)

    return "".join(visible_parts)


def describe_char_codes(value: str) -> str:
    parts: list[str] = []
    for index, character in enumerate(value):
        label = CONTROL_LABELS.get(character, character)
        if len(label) != 1:
            label = f"<{label}>"

        parts.append(f"{index}:{label}=U+{ord(character):04X}")

    return " ".join(parts)


def build_csv_row(value: str, source: str) -> dict[str, str]:
    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": source,
        "barcode_raw": value,
        "barcode_visible": visible_barcode(value),
        "barcode_repr": repr(value),
        "barcode_utf8_hex": value.encode("utf-8").hex(),
        "char_codes": describe_char_codes(value),
        "contains_rs": str(RS in value),
        "contains_gs": str(GS in value),
        "contains_eot": str(EOT in value),
    }


def append_csv_row(csv_path: Path, row: dict[str, str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    should_write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        if should_write_header:
            writer.writeheader()

        writer.writerow(row)


def read_last_csv_row(csv_path: Path) -> dict[str, str]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    if not rows:
        raise RuntimeError(f"No rows were written to {csv_path}")

    return rows[-1]


def verify_csv_round_trip(csv_path: Path, expected_value: str) -> tuple[bool, list[str]]:
    last_row = read_last_csv_row(csv_path)
    failures: list[str] = []

    if last_row["barcode_raw"] != expected_value:
        failures.append("barcode_raw changed after CSV read")

    expected_hex = expected_value.encode("utf-8").hex()
    if last_row["barcode_utf8_hex"] != expected_hex:
        failures.append("barcode_utf8_hex changed after CSV read")

    if last_row["contains_rs"] != str(RS in expected_value):
        failures.append("contains_rs mismatch")

    if last_row["contains_gs"] != str(GS in expected_value):
        failures.append("contains_gs mismatch")

    if last_row["contains_eot"] != str(EOT in expected_value):
        failures.append("contains_eot mismatch")

    return not failures, failures


def capture_scan_from_console() -> str:
    print("Scan the barcode now, then press Enter. Press Esc to cancel.")

    if sys.platform != "win32":
        print("Raw key capture is Windows-only here; falling back to stdin line input.")
        return sys.stdin.readline().rstrip("\r\n")

    import msvcrt

    captured_characters: list[str] = []
    while True:
        character = msvcrt.getwch()
        if character in {"\r", "\n"}:
            print()
            break

        if character == "\x1b":
            raise KeyboardInterrupt("Scan cancelled.")

        if character == "\b":
            if captured_characters:
                captured_characters.pop()
            continue

        if character in {"\x00", "\xe0"}:
            _ = msvcrt.getwch()
            continue

        captured_characters.append(character)
        print(visible_barcode(character), end="", flush=True)

    return "".join(captured_characters)


def run_once(barcode: str, source: str, csv_path: Path) -> int:
    row = build_csv_row(barcode, source)
    append_csv_row(csv_path, row)
    csv_ok, failures = verify_csv_round_trip(csv_path, barcode)

    print("=== Barcode Control Character Test ===")
    print(f"source: {source}")
    print(f"csv_path: {csv_path.resolve()}")
    print(f"raw_console: {barcode}")
    print(f"visible: {row['barcode_visible']}")
    print(f"repr: {row['barcode_repr']}")
    print(f"utf8_hex: {row['barcode_utf8_hex']}")
    print(f"char_codes: {row['char_codes']}")
    print(f"contains_rs: {row['contains_rs']}")
    print(f"contains_gs: {row['contains_gs']}")
    print(f"contains_eot: {row['contains_eot']}")
    print(f"csv_round_trip: {'PASS' if csv_ok else 'FAIL'}")

    if csv_ok:
        return 0

    for failure in failures:
        print(f"failure: {failure}")

    return 1


def run_self_test() -> int:
    sample = f"A{RS}B{GS}C{EOT}D"
    with tempfile.TemporaryDirectory() as temporary_directory:
        csv_path = Path(temporary_directory) / "barcode_control_test.csv"
        row = build_csv_row(sample, "self-test")
        append_csv_row(csv_path, row)
        csv_ok, failures = verify_csv_round_trip(csv_path, sample)

    assertions = [
        csv_ok,
        visible_barcode(sample) == "A<RS>B<GS>C<EOT>D",
        decode_barcode_argument(r"A\x1eB<GS>C\u0004D") == sample,
        row["barcode_utf8_hex"] == "411e421d430444",
        row["contains_rs"] == "True",
        row["contains_gs"] == "True",
        row["contains_eot"] == "True",
    ]

    if all(assertions):
        print("self-test: PASS")
        return 0

    print("self-test: FAIL")
    for failure in failures:
        print(f"failure: {failure}")

    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether barcode RS/GS/EOT control characters survive console logging and CSV round-trip.",
    )
    parser.add_argument(
        "--barcode",
        help=r"Barcode text. You can write control chars as \x1e, \x1d, \x04, <RS>, <GS>, or <EOT>.",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Capture an actual scanner input from the console until Enter.",
    )
    parser.add_argument(
        "--csv",
        default=str(Path("logs") / "barcode_control_test.csv"),
        help="CSV output path. Default: logs/barcode_control_test.csv",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in assertions without touching the default CSV.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    if args.scan:
        barcode = capture_scan_from_console()
        source = "scanner"
    elif args.barcode is not None:
        barcode = decode_barcode_argument(args.barcode)
        source = "argument"
    else:
        barcode = default_barcode()
        source = "sample"

    return run_once(barcode, source, Path(args.csv))


if __name__ == "__main__":
    raise SystemExit(main())
