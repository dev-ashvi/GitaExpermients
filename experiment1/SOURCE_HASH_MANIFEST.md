# SOURCE_HASH_MANIFEST

Frozen after identity verification and extraction QC.  
Extraction tool: `pypdf 5.8.0` (text-layer only, no OCR).  
Token estimate: harness `estimate_tokens` (~3 chars/token upper bound).

| filename | SHA-256 | file size (bytes) | page count (PDF) / chars & token est. (TXT) |
|---|---|---:|---|
| S1_Peters_2016_Obesity_RCT.pdf | `4dd1ad151a05187309bd6239d9e8aaa6f403422b303b5876c4c6043953de56be` | 328037 | pages=8 |
| S1_Peters_2016_Obesity_RCT.txt | `00eb998cf4bec162d86429e053f34fad1e2be05565c122830fd2f13b5e0f1475` | 42754 | chars=42689; tokens≈14230 |
| S2_Toews_2019_BMJ_SystematicReview.pdf | `d3c84f17a44bf8458de5ddd9105d8972157c7866e519fcf50ba23983081b3dd3` | 1003968 | pages=13 |
| S2_Toews_2019_BMJ_SystematicReview.txt | `d65112932da7fbd78d6a2cafb3396c970e6fc233f10c57620b05b597ccf2dbfc` | 86410 | chars=85518; tokens≈28506 |
| S3_McGlynn_2022_JAMANetworkOpen_MetaAnalysis.pdf | `f2712e7b901f5c29c5a6fb3ec1faa3e80b90d7485b7293bbee213f4935ce5ad0` | 1536584 | pages=19 |
| S3_McGlynn_2022_JAMANetworkOpen_MetaAnalysis.txt | `0d7efeb492e223372594fac959fbe4c9de11e4edb1fd46a23f893c92fdb579f7` | 76496 | chars=75782; tokens≈25261 |
| S4_Debras_2022_BMJ_Cohort.pdf | `4097a748b3c9050f95b69dbf8476e74f27c83a14f6afe7f5f15d074b4a0b8ba9` | 487967 | pages=12 |
| S4_Debras_2022_BMJ_Cohort.txt | `0575b494e28f05961f8908434e3c969cf6b8c1b810428863bb7c9be99733bfc3` | 88426 | chars=87935; tokens≈29312 |
| S5_WHO_2023_NSS_Guideline.pdf | `eac9098f235dc4b3a6079865aadf9515990d415974f864e8593b6096a6b7d0e3` | 981538 | pages=90 |
| S5_WHO_2023_NSS_Guideline.txt | `3c8ce24dc78ea2c6d979aa4b3b46f3acf1fc6fb5721866658123fec28bde7c7a` | 260470 | chars=257750; tokens≈85917 |
| actor_constitution_v1.md | `e321f27e4c732a3f884e9ba98830bbadc7f023fb8d436b6b008da0f1b423b105` | 11559 | document |
| witness_protocol_v1.md | `f4430318953f23c0d78b12959c9ac0617907870e05d234c921307606dda730e7` | 14437 | document |
| conversation_script_v1.md | `9d0cf02fd3f27672571c7a980e155884069635d3a27957a6a405a18b49a723ce` | 18410 | document |
| HARNESS_IMPLEMENTATION_SPEC.md | `3fc3feca9221aced5d029f7259f72883d7c675f3a5750039e3d2b4c1967c34fe` | 33920 | document |

These values are mirrored in `config/experiment_config.py` as `FROZEN_MANIFEST` (`SOURCE_HASHES` + `SOURCE_TXT_HASHES` + `DOCUMENT_HASHES`).
