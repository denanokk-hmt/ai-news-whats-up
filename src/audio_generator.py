from __future__ import annotations

import logging
import os
import subprocess
import wave
from pathlib import Path

from google import genai
from google.genai import types

from src.config import PROJECT_ROOT, output_dir
from src.retry import with_retry

logger = logging.getLogger(__name__)


def _save_wav(path: Path, pcm_data: bytes, channels: int = 1, rate: int = 24000, sample_width: int = 2) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)


def _wav_to_mp3(
    wav_path: Path,
    mp3_path: Path,
    tempo: float = 1.0,
    pitch_shift: float = 1.0,
    sample_rate: int = 24000,
) -> None:
    """
    tempo: 速度倍率（ピッチは保つ）
    pitch_shift: ピッチ倍率（< 1.0 で低く、> 1.0 で高く）
    """
    filters = []
    if pitch_shift and pitch_shift != 1.0:
        # asetrateでサンプルレートを変えるとピッチも速度も変わる。
        # その後aresampleで元のレートに戻し、atempoで速度のみを補正
        filters.append(f"asetrate={int(sample_rate * pitch_shift)}")
        filters.append(f"aresample={sample_rate}")
        filters.append(f"atempo={tempo / pitch_shift}")
    elif tempo and tempo != 1.0:
        filters.append(f"atempo={tempo}")

    # ラウドネス正規化（音量の揺れを抑え、全体的に均一なレベルに揃える）
    # I=-16 LUFS, TP=-1.5dB, LRA=11 はポッドキャスト推奨値
    filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    cmd = ["ffmpeg", "-y", "-i", str(wav_path)]
    cmd.extend(["-filter:a", ",".join(filters)])
    cmd.extend([
        "-codec:a", "libmp3lame",
        "-qscale:a", "2",
        str(mp3_path),
    ])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")


def _split_script_into_chunks(script: str, max_lines_per_chunk: int = 10) -> list[str]:
    """台本を複数のチャンクに分割（音量減衰対策）。"""
    lines = [l for l in script.split("\n") if l.strip()]
    chunks = []
    for i in range(0, len(lines), max_lines_per_chunk):
        chunks.append("\n".join(lines[i:i + max_lines_per_chunk]))
    return chunks


def _generate_chunk_wav(
    client: genai.Client,
    chunk_script: str,
    speakers: list[dict],
    model: str,
    out_path: Path,
) -> None:
    speaker_a, speaker_b = speakers[0], speakers[1]
    tts_prompt = (
        f"次の会話を{speaker_a['name']}（{speaker_a.get('role', '男性')}）と"
        f"{speaker_b['name']}（{speaker_b.get('role', '女性')}）の声で、"
        f"非常に明るく活発な雰囲気で、テンポよくスピーディーに、"
        f"歯切れ良く、間を詰めて読み上げてください。"
        f"暗い・ヒソヒソした調子は絶対に避け、最初から最後まで一定の音量を保つこと。"
        f"「えー」「えーと」「あのー」「うーん」のような間延びしたフィラーや、"
        f"語尾を伸ばす「〜よねー」「〜ですかー？」のような話し方は絶対に避け、"
        f"テキスト通りに歯切れよく発話すること。\n\n"
        f"{chunk_script}"
    )

    speech_config = types.SpeechConfig(
        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[
                types.SpeakerVoiceConfig(
                    speaker=speaker_a["name"],
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=speaker_a["voice"],
                        ),
                    ),
                ),
                types.SpeakerVoiceConfig(
                    speaker=speaker_b["name"],
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=speaker_b["voice"],
                        ),
                    ),
                ),
            ]
        )
    )

    # TTS は同一入力でも間欠的に 400 INVALID_ARGUMENT を返すことがある（サーバ側都合）。
    # 通常の決定的 400 と区別できないが、リトライで回復するケースが大半のため、
    # 音声チャンク生成に限り 400 もリトライ対象に含める。
    response = with_retry(
        client.models.generate_content,
        model=model,
        contents=tts_prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
        ),
        retryable_codes=(400, 429, 500, 502, 503, 504),
        overall_deadline=600,  # 1チャンクあたり全リトライ合計で最大 10 分
    )

    if not response.candidates:
        raise RuntimeError("No audio in response")
    audio_data = response.candidates[0].content.parts[0].inline_data.data
    if not audio_data:
        raise RuntimeError("Empty audio data")
    _save_wav(out_path, audio_data)


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-500:]}")
    return float(result.stdout.strip())


def _mix_bgm(
    voice_path: Path,
    bgm_path: Path,
    out_path: Path,
    volume: float = 0.15,
    fade_in: float = 2.0,
    fade_out: float = 2.0,
) -> None:
    duration = _probe_duration(voice_path)
    fade_out_start = max(0.0, duration - fade_out)
    bgm_chain = (
        f"[1:a]volume={volume},"
        f"afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={fade_out_start}:d={fade_out}[bgm]"
    )
    mix = "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[out]"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_path),
        "-stream_loop", "-1", "-i", str(bgm_path),
        "-filter_complex", f"{bgm_chain};{mix}",
        "-map", "[out]",
        "-codec:a", "libmp3lame",
        "-qscale:a", "2",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg bgm mix failed: {result.stderr[-500:]}")


def _concat_wavs(wav_paths: list[Path], out_path: Path) -> None:
    """複数WAVを連結（無音区切りを少し挟む）。"""
    list_file = out_path.parent / "concat_list.txt"
    list_file.write_text("\n".join(f"file '{p.absolute()}'" for p in wav_paths))
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {result.stderr[-500:]}")


def generate_audio(
    script: str,
    model: str,
    speakers: list[dict],
    tempo: float = 1.0,
    pitch_shift: float = 1.0,
    chunk_lines: int = 10,
    bgm: dict | None = None,
) -> Path:
    if len(speakers) != 2:
        raise ValueError(f"Expected 2 speakers, got {len(speakers)}")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=180_000),  # 3 分（無通信タイムアウト）
    )

    chunks = _split_script_into_chunks(script, max_lines_per_chunk=chunk_lines)
    logger.info("Generating audio in %d chunks (%d chars total)...",
                len(chunks), len(script))

    out = output_dir()
    wav_paths = []
    for i, chunk in enumerate(chunks, 1):
        chunk_wav = out / f"chunk_{i:02d}.wav"
        logger.info("  Chunk %d/%d (%d chars)...", i, len(chunks), len(chunk))
        _generate_chunk_wav(client, chunk, speakers, model, chunk_wav)
        wav_paths.append(chunk_wav)

    merged_wav = out / "episode_merged.wav"
    _concat_wavs(wav_paths, merged_wav)
    logger.info("Concatenated %d chunks: %s (%.1f KB)",
                len(wav_paths), merged_wav, merged_wav.stat().st_size / 1024)

    mp3_path = out / "episode.mp3"
    voice_only_path = out / "voice_only.mp3" if (bgm and bgm.get("enabled")) else mp3_path
    _wav_to_mp3(merged_wav, voice_only_path, tempo=tempo, pitch_shift=pitch_shift)
    logger.info("Saved voice MP3: %s (%.1f KB, tempo=%.2fx, pitch=%.2fx)",
                voice_only_path, voice_only_path.stat().st_size / 1024, tempo, pitch_shift)

    if bgm and bgm.get("enabled"):
        bgm_path = PROJECT_ROOT / bgm["path"]
        if not bgm_path.exists():
            raise RuntimeError(f"BGM file not found: {bgm_path}")
        _mix_bgm(
            voice_only_path, bgm_path, mp3_path,
            volume=bgm.get("volume", 0.15),
            fade_in=bgm.get("fade_in", 2.0),
            fade_out=bgm.get("fade_out", 2.0),
        )
        logger.info("Mixed BGM: %s (%.1f KB, vol=%.2f)",
                    mp3_path, mp3_path.stat().st_size / 1024, bgm.get("volume", 0.15))
        voice_only_path.unlink(missing_ok=True)

    # 中間ファイルクリーンアップ
    for p in wav_paths:
        p.unlink(missing_ok=True)
    merged_wav.unlink(missing_ok=True)

    return mp3_path
