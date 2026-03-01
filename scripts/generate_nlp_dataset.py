import json
import random
from pathlib import Path

random.seed(42)

TEMPLATES = {
    "Makanan": [
        "saya makan di {place}",
        "makan siang di {place}",
        "sarapan {food} di {place}",
        "jajan {food}",
        "beli makan {food}",
    ],
    "Transportasi": [
        "naik {mode} ke kantor",
        "isi bensin di {place}",
        "bayar parkir di {place}",
        "pesan ojol ke {place}",
        "naik taksi dari rumah ke {place}",
    ],
    "Belanja": [
        "belanja di {place}",
        "beli {item} di {place}",
        "checkout {item} di shopee",
        "belanja bulanan di {place}",
        "beli kebutuhan rumah tangga",
    ],
    "Lifestyle": [
        "nonton bioskop di {place}",
        "main game dan topup",
        "ngopi di {place}",
        "hangout di {place}",
        "bayar gym bulanan",
    ],
    "Tagihan": [
        "bayar listrik bulan ini",
        "bayar internet rumah",
        "bayar air pdam",
        "bayar cicilan kartu kredit",
        "bayar pulsa hp",
    ],
    "Kesehatan": [
        "beli obat di {place}",
        "periksa ke dokter di {place}",
        "tebus resep di apotek",
        "bayar klinik kesehatan",
        "beli vitamin",
    ],
    "Sosial": [
        "kirim donasi ke panti",
        "sedekah jumat",
        "kasih hadiah ulang tahun",
        "transfer uang ke teman",
        "zakat bulanan",
    ],
    "Pendidikan": [
        "bayar kursus online",
        "beli buku pelajaran",
        "bayar spp sekolah",
        "bayar ukt kuliah",
        "ikut pelatihan kerja",
    ],
    "Lain-lain": [
        "rapat sore dengan tim",
        "lagi capek banget hari ini",
        "besok mau olahraga pagi",
        "baca buku di rumah",
        "ngobrol santai sama teman",
    ],
}

VALUES = {
    "place": ["warteg", "indomaret", "alfamart", "mall", "kantin", "plaza", "terminal", "kampus"],
    "food": ["nasi padang", "bakso", "mie ayam", "ayam geprek", "soto"],
    "mode": ["gojek", "grab", "bus", "kereta", "mrt"],
    "item": ["sabun", "baju", "sepatu", "charger", "beras"],
}


def render(template: str) -> str:
    out = template
    for k, arr in VALUES.items():
        token = "{" + k + "}"
        if token in out:
            out = out.replace(token, random.choice(arr))
    # occasional amount noise
    if random.random() < 0.6:
        amount = random.choice(["10rb", "25rb", "50rb", "100rb", "2jt"])
        out = f"{out} {amount}"
    return out


def generate(min_rows=1200):
    rows = []
    labels = list(TEMPLATES.keys())
    idx = 0
    while len(rows) < min_rows:
        label = labels[idx % len(labels)]
        tpl = random.choice(TEMPLATES[label])
        txt = render(tpl)
        rows.append({"text": txt, "category": label})
        idx += 1
    return rows


def main():
    rows = generate(1200)
    p = Path("data/nlp_id_daily_1000.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"written={len(rows)} -> {p}")


if __name__ == "__main__":
    main()
