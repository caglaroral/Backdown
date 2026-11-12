# Immich: kurulum ve ayarlar

Telefon galerilerini 1.190 üzerindeki Immich'e, oradan da WD My Book World NAS'a yedekleyen kurulum.

## Mimari

```
Telefonlar ──Wi-Fi──► 1.190:2283 (Immich, Docker)
                          │  orijinaller (NFS)        küçük resim / video / DB (yerel disk)
                          ▼                            ▼
              NAS 10.42.0.226:/nfs/immich     ~/immich-app/local/*, ~/immich-app/postgres
```

| Bileşen | Değer |
|---|---|
| Sunucu | 1.190 (Fujitsu ESPRIMO Q510, Debian 13) |
| Web arayüzü | http://192.168.1.190:2283 (yalnızca yerel ağ) |
| Sürüm | Immich v3 (`IMMICH_VERSION=v3`), docker compose |
| Kurulum klasörü | `~/immich-app/` (`docker-compose.yml`, `.env`) |
| Orijinal dosyalar | `/mnt/immich`: NAS'taki `immich` paylaşımı (NFSv3) |
| Küçük resimler | `~/immich-app/local/thumbs` (yerel disk) |
| Dönüştürülmüş videolar | `~/immich-app/local/encoded-video` (yerel disk) |
| Veritabanı | `~/immich-app/postgres` (yerel disk, `DB_STORAGE_TYPE: 'HDD'`) |

NAS çok yavaş olduğu için küçük resimler, dönüştürülmüş videolar ve veritabanı yerel diskte duruyor. NAS'a yalnızca orijinal dosyalar yazılıyor.

## 1.190 üzerindeki yapılandırma

**`.env`** (dosya izni `600`; `DB_PASSWORD` rastgele üretildi, bu belgede yok):

```
UPLOAD_LOCATION=/mnt/immich
DB_DATA_LOCATION=./postgres
TZ=Europe/Istanbul
IMMICH_VERSION=v3
DB_USERNAME=postgres
DB_DATABASE_NAME=immich
```

**`docker-compose.yml`:** `immich-server` için standart dosyaya şu iki volume satırı eklendi:

```yaml
    volumes:
      - ${UPLOAD_LOCATION}:/data
      - ./local/thumbs:/data/thumbs
      - ./local/encoded-video:/data/encoded-video
```

Ayrıca `database` servisinde `DB_STORAGE_TYPE: 'HDD'` açık.

**`/etc/fstab`** (yedeği: `/etc/fstab.bak-20261111`):

```
10.42.0.226:/nfs/immich /mnt/immich nfs vers=3,proto=tcp,hard,timeo=600,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=30 0 0
10.42.0.226:/nfs/caglar /mnt/caglar nfs vers=3,proto=tcp,hard,timeo=600,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=30 0 0
```

**NAS'ın IP adresi:**
- NAS, 1.190'ın `enp0s25` arayüzüne doğrudan bağlı. Bu bağlantı NetworkManager'ın "shared" modunda çalışıyor (`10.42.0.1/24`).
- NAS'ın IP'si iki yerden sabitlendi:
  - `/etc/NetworkManager/dnsmasq-shared.d/nas-static.conf` → `dhcp-host=00:90:a9:71:52:78,10.42.0.226,mybookworld,infinite`
  - NAS'ın web arayüzünde de statik IP olarak ayarlandı.

**`.immich` işaret dosyaları:** Immich, `/mnt/immich` altındaki şu klasörlerin her birinde bir `.immich` dosyası arar:
- `library`
- `upload`
- `profile`
- `backups`
- `thumbs`
- `encoded-video`

Bu dosyalar yoksa açılmaz. Depolama yeri değiştirilirse bu dosyalar da yeni yere kopyalanmalı.

**Diğer:** `sky` kullanıcısı `docker` grubunda.

## İlk kurulum (web arayüzü)

Sırası önemli: **depolama şablonu ilk fotoğraf yüklenmeden önce açılmalı.** Sonradan açılırsa Immich önceden yüklenmiş bütün dosyaları yeni klasörlerine taşır. Bu toplu taşıma NAS'ı zorlar.

1. **Yönetici hesabı:** http://192.168.1.190:2283 adresini aç ve ilk hesabı oluştur. İlk hesap yönetici olur.
2. **Depolama şablonu** (*Administration → Settings → Storage Template*):
   - Enable: **açık**
   - Şablon, Media klasörüyle aynı düzende olsun:
     ```
     {{y}}/{{y}}-{{MM}}/{{y}}{{MM}}{{dd}}_{{HH}}{{mm}}{{ss}}_{{filename}}
     ```
     Uzantıyı Immich kendisi ekler. Aynı ad iki kez çıkarsa Immich sona `+1` ekler.
3. **Kullanıcılar ve depolama etiketleri** (*Administration → Users*):
   - Kendi kullanıcın: Storage Label = `caglar`
   - İkinci kişi için yeni bir kullanıcı oluştur. Ona da kendi etiketini ver (örneğin `esim`).
   - Dosyalar `library/<etiket>/YYYY/YYYY-MM/...` altına yazılır. Böylece her kişinin fotoğrafları ayrı klasörde durur.
   - Etiket verilmeyen kullanıcının dosyaları, kullanıcı kimliğiyle adlandırılmış (UUID) bir klasöre gider.
4. **İş ayarları:** NAS'ı yormamak için aşağıdaki bölüme göre ayarla.

## NAS için yavaş ayarlar

NAS (ARM926 işlemci, 128 MB RAM) art arda gelen yüke dayanamıyor. Toplu işlemlerde NFS, var olan dosyalar için ara sıra "No such file" cevabı veriyor. Bu nedenle bütün arka plan işleri tek tek yapılmalı.

*Administration → Settings → Job Settings* (iş eşzamanlılığı; sürüme göre bölümün adı farklı olabilir):

| İş | Varsayılan | Önerilen | NAS'a yük |
|---|---|---|---|
| Thumbnail Generation | 3 | **1** | Orijinali NAS'tan okur |
| Metadata Extraction | 5 | **1** | Orijinali NAS'tan okur |
| Video Conversion | 1 | **1** | Orijinali NAS'tan okur, uzun sürer |
| Smart Search | 2 | 1 | Yereldeki küçük resmi okur |
| Face Detection | 2 | 1 | Yereldeki küçük resmi okur |
| Sidecar / Library | — | 1 | |

Diğer ayarlar:
- **Video dönüştürme** (*Video Transcoding Settings*): Transcode policy olarak "Videos not in an accepted format" seçilsin. Böylece telefonların zaten oynatılabilir videoları yeniden kodlanmaz.
- **Dış kütüphane (External Library):** `/mnt/caglar/Media` **eklenmeyecek.** Taranması NAS'ı saatlerce yorar.

## Telefon uygulaması

1. Immich uygulamasını kur. Sunucu adresi: `http://192.168.1.190:2283`. Bu adres yalnızca ev ağında çalışır.
2. Kendi kullanıcınla giriş yap. Her kişi kendi hesabını kullanmalı, yoksa depolama etiketi işe yaramaz.
3. **İlk yedekleme parça parça yapılsın:** *Backup* ekranında önce bir iki albüm seç (örneğin yalnızca *Camera*). Onlar bitip arka plan işleri durulduktan sonra (*Administration → Jobs*) yeni albümleri ekle.
4. Yedekleme yalnızca Wi-Fi'da ve şarjdayken yapılsın (uygulama ayarları).

## Kontrol ve bakım

```sh
cd ~/immich-app
docker compose ps                     # dört servis "healthy" olmalı
docker compose logs -f immich-server  # canlı log
curl -s http://localhost:2283/api/server/ping   # {"res":"pong"}
mount | grep /mnt/immich              # NFS bağlı mı
```

- **Güncelleme:** `docker compose pull && docker compose up -d`. `IMMICH_VERSION=v3` olduğu için v3 içinde kalır. Yeni ana sürüme geçmeden önce sürüm notlarını oku.
- **Veritabanı yedeği:** Immich her gece veritabanının dökümünü `/mnt/immich/backups` klasörüne yazar, yani NAS'a.

## Uyarılar

- **NAS diskleri arızalı (2026-11-11 SMART ölçümü):**

  | Disk | Yedekle değiştirilmiş bölge | Okunamayan, bekleyen bölge | Diğer |
  |---|---|---|---|
  | `sdb` | 343 | 229 | Okuma (UNC) hataları |
  | `sda` | 0 | 5 | |

  - RAID1 şimdilik sağlam (`[UU]`), ama Immich'teki orijinaller de aynı disklerde duruyor.
  - Telefonlardaki fotoğraflar, NAS dışında ikinci bir yedek alınmadan silinmemeli.
- **NFS takılması:** 1.190'da bir dosya "yok" görünürse önce NAS'a ssh ile bağlanıp dosyanın orada olup olmadığına bak. Sorun çoğunlukla geçicidir. Dosya orada ama görünmüyorsa bağlantıyı yeniden kur:
  ```sh
  sudo umount /mnt/immich && sudo mount /mnt/immich
  ```
  Bunu yapmadan önce Immich'i durdur (`docker compose stop`) ve sonra yeniden başlat.
