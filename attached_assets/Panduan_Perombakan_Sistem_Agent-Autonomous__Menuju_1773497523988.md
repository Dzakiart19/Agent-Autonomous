# Panduan Perombakan Sistem Agent-Autonomous: Menuju Transparansi ala Manus.im

Dokumen ini disusun berdasarkan analisis mendalam terhadap repositori **Agent-Autonomous**. Masalah utama yang Anda hadapi—di mana AI bekerja secara "gaib" dan hanya memunculkan file jadi tanpa memperlihatkan proses kodenya—disebabkan oleh ketidakselarasan antara **System Prompt**, **Mekanisme Streaming**, dan **UI Rendering**.

Berikut adalah langkah-langkah strategis untuk merombak sistem Anda agar memiliki transparansi dan keandalan kerja seperti **Manus.im**.

---

## 1. Perombakan System Prompt (The "Brain" Logic)

Masalah Anda bukan hanya di sandbox, tapi di bagaimana AI diperintahkan untuk melapor. Manus.im selalu diperintahkan untuk **menuliskan pemikirannya (Chain of Thought)** dan **melaporkan setiap aksi** sebelum mengeksekusinya.

### Rekomendasi Perubahan `server/agent/prompts/system.py`:

Tambahkan blok instruksi berikut untuk memaksa AI mengekspos kodenya:

```markdown
<reporting_rules>
1. **Transparansi Kode**: Sebelum menulis file besar atau menjalankan script kompleks, berikan ringkasan logika atau potongan kode penting melalui `message_notify_user`.
2. **Live Progress**: Gunakan `message_notify_user` untuk melaporkan apa yang sedang Anda lakukan di dalam sandbox (misal: "Sedang menginstal dependensi...", "Mulai menulis logika inti di test.py...").
3. **Verifikasi Output**: Setelah menjalankan perintah shell, Anda HARUS membaca kembali file yang dibuat (`file_read`) untuk memastikan isinya benar, dan laporkan ringkasannya ke user.
</reporting_rules>
```

---

## 2. Mekanisme Streaming Output (The "Live" View)

Alasan Anda hanya melihat "file jadi" adalah karena sistem Anda kemungkinan besar menunggu fungsi `execute_tool` selesai (blocking) baru mengirimkan hasilnya ke UI. Manus.im menggunakan **Streaming Tool Output**.

### Perbaikan pada `server/agent/agent_flow.py`:

Anda sudah memiliki `tool_stream` di kode Anda, namun pastikan `shell_exec` di E2B benar-benar mengirimkan data secara *real-time*.

**Poin Penting:**
*   Pastikan `on_stdout` dan `on_stderr` di E2B Sandbox memicu event `tool_stream` ke frontend **seketika** saat karakter muncul, bukan menunggu perintah selesai.
*   Gunakan `sys.stdout.reconfigure(line_buffering=True)` di dalam sandbox agar output Python tidak tertahan di buffer.

---

## 3. Sinkronisasi File & Visibilitas (The "Sandbox" Sync)

Anda menyebutkan "hanya melihat file yang sudah dibuat bukan isi yang dibuat". Ini terjadi karena file berada di **E2B Sandbox (Cloud)**, sedangkan UI Anda mungkin hanya membaca metadata atau file yang sudah di-sync ke lokal.

### Strategi "Read-After-Write":
Ubah logika `file_write` Anda. Jangan hanya mengembalikan status "Success". Kembalikan **potongan isi file** yang baru saja ditulis dalam `ToolResult`.

**Modifikasi `server/agent/tools/file.py`:**
```python
def file_write(file, content, ...):
    # ... kode penulisan ke E2B ...
    
    # Tambahkan ini:
    preview = content[:1000] + "..." if len(content) > 1000 else content
    return ToolResult(
        success=True,
        message=f"File written to {file}. Content preview:\n```python\n{preview}\n```",
        data={"file": file, "content": preview} # Kirim konten ke UI
    )
```

---

## 4. Perbaikan UI Rendering (The "Visual" Feedback)

Agar terlihat seperti Manus, UI harus bisa merender **Markdown** di dalam bubble "Thinking" atau "Tool Result".

### Update `components/AgentToolView.tsx`:
Pastikan komponen `FileContent` atau `ShellContent` Anda menggunakan library syntax highlighting (seperti `react-native-syntax-highlighter` atau `react-markdown` dengan `remark-gfm`).

**Logika Manus:**
*   Saat `status === "calling"`, tampilkan argumen fungsi (misal: `command: python3 test.py`).
*   Saat `status === "called"`, tampilkan `functionResult` yang berisi kode/output tadi.

---

## 5. Arsitektur Sandbox E2B yang Ideal

Untuk menghindari hasil yang "ngaco", sandbox harus memiliki **State Persistence** yang kuat.

| Komponen | Rekomendasi |
| :--- | :--- |
| **Workspace** | Gunakan direktori tetap (misal: `/home/user/project`) dan pastikan AI selalu `cd` ke sana. |
| **Environment** | Selalu jalankan `pip install` dengan `--break-system-packages` di E2B agar tidak konflik dengan sistem. |
| **Visibility** | Gunakan `ls -R` secara berkala secara otomatis (hidden task) untuk memperbarui daftar file di UI. |

---

## Kesimpulan & Action Plan

1.  **Rombak System Prompt**: Tambahkan aturan `<reporting_rules>` agar AI lebih cerewet soal apa yang dia tulis.
2.  **Update Tool Result**: Paksa `file_write` dan `shell_exec` untuk selalu menyertakan cuplikan konten/output di dalam pesan balasan.
3.  **Frontend Highlight**: Pastikan UI Anda tidak hanya menampilkan nama file, tapi merender isi `data.content` yang dikirim dari backend.

Dengan menerapkan perubahan ini, Agent-Autonomous Anda tidak akan lagi bekerja dalam "gelap", dan Anda bisa melihat setiap baris kode yang ditulis AI secara real-time.
