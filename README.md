# A加z分數 + T原版 — 平行forward paper track

跟 [crypto_combo_forward](https://github.com/pidasin/crypto_combo_forward) 的差異:
A腿在原本4象限方向上,乘上「CB溢價偏離90日常態的z分數強度」(0~100%,不加槓桿)。
T腿完全不變(SMA50二元開關)。

這是根據9年回測+統計檢驗(Sharpe標準誤差、拿掉爆發期後穩健性、OOS測試期表現)選出的候選版本。
純訊號+模擬帳本,不接真實下單。目的是觀察真實時間裡的forward表現,
之後再決定要不要正式換掉現行系統。

起算日: 2026-07-13
