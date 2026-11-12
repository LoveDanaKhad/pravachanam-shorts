# Pravachanam Shorts

Windows app that turns long pravachanams (Telugu, Hindi, English, with Sanskrit quotes) into vertical
YouTube Shorts with English and Russian subtitles, in an approved design template.

Pipeline: speech recognition (AI4Bharat IndicConformer, ONNX, runs on the computer) → DeepSeek chooses
complete-thought fragments → user approves → DeepSeek splits the text into subtitles by sense and translates →
user checks the text → ffmpeg renders the Shorts.

No API keys, videos or texts are stored in this repository: they stay on the user's computer.

Fonts: Fraunces, Cormorant Garamond, Inter, Noto Sans Telugu, Noto Sans Devanagari — SIL Open Font License 1.1
(static instances renamed "PS …"). Speech models are downloaded on install from Hugging Face (MIT licence).
