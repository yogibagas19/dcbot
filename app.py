import discord
from discord.ext import commands
from qbittorrent import Client
import logging
import os
import subprocess
import glob
import shutil
import asyncio
import time
from dotenv import load_dotenv
from concurrent.futures import ProcessPoolExecutor

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("TorrentBot")

# inisialisasi bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

token = os.getenv("DISCORD_TOKEN")

DOWNLOAD_DIR = '/backup/Downloads'

movies_dir = "/home/movies"

admin_channel_id = int(os.getenv("ADMIN_CHANNEL_ID"))

qb = Client("http://127.0.0.1:8080")
qb.login("admin", "adminadmin")

def convert_to_mp4(file_path, progress_callback):
    """
    Mengonversi file MKV ke MP4 menggunakan FFmpeg.
    """
    try:
        output_path = file_path.replace(".mkv", ".mp4")
        command = [
            "ffmpeg",
            "-i", file_path,       # Input file
            "-codec:v", "libx264", # Codec video
            "-crf", "23",          # Kualitas video (23 adalah kualitas standar)
            "-preset", "medium",   # Kecepatan encoding
            "-codec:a", "aac",     # Codec audio
            "-b:a", "192k",        # Bitrate audio
            "-threads", "1",       # Jumlah thread
            output_path
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while True:
            output = process.stderr.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                progress_callback(output.strip())
        return output_path
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to convert {file_path}: {e}")
        raise Exception(f"Gagal mengonversi {file_path}: {e}")

def rename_file(old_path, new_name):
    """
    Mengganti nama file.
    """
    new_path = os.path.join(os.path.dirname(old_path), new_name)
    os.rename(old_path, new_path)
    return new_path

def get_active_torrents():
    """
    Fetch the status of torrents that are currently downloading or have finished downloading.
    """
    torrents = qb.torrents()
    active_torrents = []
    for torrent in torrents:
        if torrent['state'] == 'downloading':
            status = {
                'name': torrent['name'],
                'progress': torrent['progress'] * 100,  # Convert to percentage
                'state': torrent['state']
            }
            active_torrents.append(status)
        elif torrent['state'] == 'stalledUP':
            status = {
                'name': torrent['name'],
                'progress': torrent['progress'] * 100,  # Convert to percentage
                'state': torrent['state']
            }
            active_torrents.append(status)
        elif torrent['state'] == 'uploading':
            # Pause the torrent if it has finished downloading
            qb.pause(torrent['hash'])
            status = {
                'name': torrent['name'],
                'progress': torrent['progress'] * 100,  # Convert to percentage
                'state': 'paused'
            }
            active_torrents.append(status)
    return active_torrents

def delete_old_files(directory, days=2):

    now = time.time()
    cutoff = now - (days * 86400)  # 86400 detik dalam sehari

    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            if os.path.isfile(file_path):
                file_mtime = os.path.getmtime(file_path)
                if file_mtime < cutoff:
                    try:
                        os.remove(file_path)
                        logger.info(f"File {file_path} berhasil dihapus karena lebih tua dari {days} hari.")
                    except Exception as e:
                        logger.error(f"Error menghapus file {file_path}: {e}")

@bot.event
async def on_ready():
    print(f"Bot {bot.user} sudah online")
    logger.info(f"Bot {bot.user} sudah siap digunakan")
    bot.loop.create_task(update_torrent_status())
    bot.loop.create_task(delete_old_files_task())

async def delete_old_files_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        delete_old_files(DOWNLOAD_DIR, days=2)
        await asyncio.sleep(86400)

async def update_torrent_status():
    await bot.wait_until_ready()
    channel = bot.get_channel(admin_channel_id)
    message = None

    while not bot.is_closed():
        status_list = get_active_torrents()
        if status_list:
            embed = discord.Embed(
                title="Status Torrent",
                color=discord.Color.blue()
            )
            for status in status_list:
                embed.add_field(
                    name=status['name'],
                    value=f"Progress: {status['progress']:.2f}%\nState: {status['state']}",
                    inline=False
                )

            if message is None:
                message = await channel.send(embed=embed)
            else:
                await message.edit(embed=embed)
        await asyncio.sleep(1)

# menambahkan torrent melalui magnet link
@bot.command()
async def addMagnet(ctx, link: str):
    try:
        qb.download_from_link(link)
        logger.info(f"User {ctx.author} menambahkan magnet link : {link}")
        await ctx.send(f"Magnet link berhasil ditambahkan: {link}")
    except Exception as e:
        logger.error(f"Error menambahkan mager link : {e}")
        await ctx.send(f"Gagal menambahkan magnet link : {e}")

# menambahkan torrent melalui attach file
@bot.command()
async def addTorrent(ctx):
    if len(ctx.message.attachments) > 0:
        attachment = ctx.message.attachments[0]
        file_path = f"./file/{attachment.filename}"
        await attachment.save(file_path)

        try:
            qb.download_from_file(open(file_path, 'rb'))
            logger.info(f"User {ctx.author} menambahkan file torrent: {attachment.filename}")
            await ctx.send(f"Torrent file berhasil ditambahkan: {attachment.filename}")
        except Exception as e:
            logger.error(f"Error menambahkan torrent file: {e}")
            await ctx.send(f"Gagal menambahkan torrent file: {e}")
        
    else:
        await ctx.send("Harap lampirkan file .torrent")

# memeriksa status torrent
@bot.command()
async def torrentStatus(ctx):
    torrents = qb.torrents()
    if torrents:
        status = "\n".join([f"{t['name']} - {t['state']}" for t in torrents])
        await ctx.send(f"Status torrent: \n{status}")
    else:
        await ctx.send("Tidak ada torrent yang sedang aktif.")

# menghapus torrent
@bot.command()
async def deleteTorrent(ctx, torrent_name: str):
    torrents = qb.torrents()
    for torrent in torrents:
        if torrent_name.lower() in torrent["name"].lower():
            qb.delete(torrent['hash'])
            logger.info(f"User {ctx.author} menghapus torrent: {torrent['name']}")
            await ctx.send(f"Torrent '{torrent['name']}' berhasil dihapus.")
            return
    
    await ctx.send(f"Torrent dengan nama '{torrent['name']}' tidak ditemukan.")

# melanjutkan download yang sedang terhenti
@bot.command()
async def resumeAll(ctx):
    try:
        qb.resume_all()
        logger.info(f"User {ctx.author} memulai ulang semua torrent yang paused.")
        await ctx.send("Semua torrent yang paused berhasil dimulai ulang.")
    except Exception as e:
        logger.error(f"Error memulai ulang torrent: {e}")
        await ctx.send(f"Gagal memulai ulang torrent: {e}")

# convert file menggunakan ffmpeg
@bot.command()
async def convert(ctx, file_name: str):
    """
    Command untuk mengonversi file MKV ke MP4.
    """
    try:
        search_pattern = os.path.join(DOWNLOAD_DIR, '**', file_name)
        file_paths = glob.glob(search_pattern, recursive=True)

        if not file_paths:
            embed = discord.Embed(
                title="File Tidak Ditemukan",
                description=f"File `{file_name}` tidak ditemukan di folder unduhan.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        file_path = file_paths[0]

        if not file_name.endswith(".mkv"):
            embed = discord.Embed(
                title="Ekstensi File Tidak Didukung",
                description="Hanya file dengan ekstensi `.mkv` yang bisa dikonversi.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="Proses Konversi",
            description=f"Sedang mengonversi file `{file_name}`...",
            color=discord.Color.blue()
        )
        message = await ctx.send(embed=embed)

        def progress_callback(progress):
            if "time=" in progress:
                time_str = progress.split("time=")[-1].split(" ")[0]
                embed.description = f"Sedang mengonversi file `{file_name}`...\nWaktu: {time_str}"
                asyncio.run_coroutine_threadsafe(message.edit(embed=embed), bot.loop)

        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor() as pool:
            converted_path = await loop.run_in_executor(pool, convert_to_mp4, file_path, progress_callback)
        
        # Move the converted file to the specified path
        destination_path = os.path.join("/home/movies", os.path.basename(converted_path))
        shutil.move(converted_path, destination_path)
        
        embed = discord.Embed(
            title="Konversi Berhasil",
            description=f"Berhasil mengonversi dan memindahkan file ke: {destination_path}",
            color=discord.Color.green()
        )
        await message.edit(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="Kesalahan",
            description=f"Terjadi kesalahan saat konversi: {e}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command()
async def rename(ctx, old_name: str, new_name: str):

    try:
        old_path = os.path.join("/home/movies", old_name)

        if not os.path.exists(old_path):
            embed = discord.Embed(
                title="File Tidak Ditemukan",
                description=f"File `{old_name}` tidak ditemukan di folder unduhan.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        new_path = rename_file(old_path, new_name)
        embed = discord.Embed(
            title="Penggantian Nama Berhasil",
            description=f"Berhasil mengganti nama file menjadi: {new_path}",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

        channel = bot.get_channel(admin_channel_id)
        if channel:
            await channel.send(f"File `{old_name}` telah diganti menjadi `{new_name}`.")
    except Exception as e:
        embed = discord.Embed(
            title="Kesalahan",
            description=f"Terjadi kesalahan saat mengganti nama: {e}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command()
async def listFiles(ctx):

    allowed_extensions = {".mkv", ".mp4", ".srt", ".ass", ".vtt"}
    file_list = []

    for root, _, files in os.walk(DOWNLOAD_DIR):
        for file in files:
            if any(file.endswith(ext) for ext in allowed_extensions):
                # Menyimpan file dengan path relatif terhadap DOWNLOAD_DIR
                relative_path = os.path.relpath(os.path.join(root, file), DOWNLOAD_DIR)
                file_list.append(relative_path)

    if file_list:
        # Membatasi panjang pesan agar tidak melebihi batas Discord (2000 karakter)
        chunk_size = 1900  # Beri ruang untuk format teks
        file_list_str = "\n".join(file_list)
        no = 1
        for i in range(0, len(file_list_str), chunk_size):
            chunk = file_list_str[i:i+chunk_size]
            numbered_chunk = "\n".join([f"{no + idx}. {line}" for idx, line in enumerate(chunk.split('\n'))])
            await ctx.send(f"File yang tersedia:\n```\n{numbered_chunk}\n```")
            no += len(chunk.split('\n'))
    else:
        await ctx.send("Tidak ada file yang cocok ditemukan di folder unduhan.")

@bot.command()
async def listMovies(ctx):

    movies_dir = "/home/movies"
    allowed_extensions = {".mkv", ".mp4", ".srt", ".ass", ".vtt"}
    movie_list = []

    for root, _, files in os.walk(movies_dir):
        for file in files:
            if any(file.endswith(ext) for ext in allowed_extensions):
                # Menyimpan file dengan path relatif terhadap movies_dir
                relative_path = os.path.relpath(os.path.join(root, file), movies_dir)
                movie_list.append(relative_path)

    if movie_list:
        # Membatasi panjang pesan agar tidak melebihi batas Discord (2000 karakter)
        chunk_size = 1900  # Beri ruang untuk format teks
        movie_list_str = "\n".join(movie_list)
        no = 1
        for i in range(0, len(movie_list_str), chunk_size):
            chunk = movie_list_str[i:i+chunk_size]
            numbered_chunk = "\n".join([f"{no + idx}. {line}" for idx, line in enumerate(chunk.split('\n'))])
            await ctx.send(f"Film yang tersedia:\n```\n{numbered_chunk}\n```")
            no += len(chunk.split('\n'))
    else:
        await ctx.send("Tidak ada film yang cocok ditemukan di folder movies.")

@bot.command()
async def deleteMovie(ctx, *, movie_name: str):

    movies_dir = "/home/movies"
    movie_path = os.path.join(movies_dir, movie_name)

    if os.path.exists(movie_path):
        try:
            os.remove(movie_path)
            await ctx.send(f"Film `{movie_name}` berhasil dihapus.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan saat menghapus film: {e}")
    else:
        await ctx.send(f"Film `{movie_name}` tidak ditemukan di folder movies.")

@bot.command()
async def helpme(ctx):
    embed = discord.Embed(
        title="Bantuan",
        description="Berikut adalah daftar perintah yang dapat digunakan:",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="!addMagnet",
        value="Menambahkan torrent menggunakan magnet link.",
        inline=False
    )
    embed.add_field(
        name="!addTorrent",
        value="Menambahkan torrent menggunakan file .torrent yang dilampirkan.",
        inline=False
    )
    embed.add_field(
        name="!torrentStatus",
        value="Melihat status torrent yang sedang aktif.",
        inline=False
    )
    embed.add_field(
        name="!deleteTorrent",
        value="Menghapus torrent berdasarkan nama.",
        inline=False
    )
    embed.add_field(
        name="!resumeAll",
        value="Melanjutkan semua torrent yang sedang terhenti.",
        inline=False
    )
    embed.add_field(
        name="!convert",
        value="Mengonversi file MKV ke MP4.",
        inline=False
    )
    embed.add_field(
        name="!rename",
        value="Mengganti nama file yang sudah dikonversi.",
        inline=False
    )
    embed.add_field(
        name="!listFiles",
        value="Melihat daftar file yang ada di folder unduhan.",
        inline=False
    )
    embed.add_field(
        name="!listMovies",
        value="Melihat daftar film yang ada di folder movies.",
        inline=False
    )
    embed.add_field(
        name="!deleteMovie",
        value="Menghapus film berdasarkan nama.",
        inline=False
    )

    await ctx.send(embed=embed)

bot.run(token)