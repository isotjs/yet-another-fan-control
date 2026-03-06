"""
translations.py — tr/en string for hp-fan-tui
"""

STRINGS: dict[str, dict[str, str]] = {
    "tr": {
        # ── Binding etiketleri ─────────────────────────────────────────────
        "quit":                "Çıkış",
        "refresh":             "Yenile",
        "copy":                "Kopyala",
        "mode_max":            "MAX mod",
        "mode_auto":           "AUTO mod",
        "mode_manual":         "MANUAL mod",
        "add":                 "Ekle",
        "delete":              "Sil",
        "cancel":              "İptal",
        # ── Üst bar butonları ─────────────────────────────────────────────
        "btn_max":             "1: MAX",
        "btn_auto":            "2: AUTO",
        "btn_manual":          "3: MANUAL",
        "svc_start":           "Başlat",
        "svc_stop":            "Durdur",
        "svc_restart":         "Yeniden Başlat",
        # ── Panel başlıkları ──────────────────────────────────────────────
        "panel_temps":         "SICAKLIKLAR",
        "panel_fans":          "FANLAR",
        "panel_curve":         "FAN EĞRİSİ  (MANUAL modda düzenlemek için Enter/tıkla)",
        "panel_log":           "LOG  (journalctl -u hp-fan-curve)",
        # ── Tablo sütunları ───────────────────────────────────────────────
        "col_threshold":       "Eşik (°C)",
        "col_rpm":             "Fan RPM",
        "col_status":          "Durum",
        "active_marker":       "← AKTİF",
        # ── Servis etiketi ────────────────────────────────────────────────
        "service_label":       "Servis",
        # ── Log mesajları ─────────────────────────────────────────────────
        "mode_changed":        "[Mod değişti → {mode}]",
        "edit_only_manual":    "[Düzenleme sadece MANUAL modda aktif — önce 3'e basın]",
        "add_only_manual":     "[Kademe ekleme sadece MANUAL modda aktif — önce 3'e basın]",
        "del_only_manual":     "[Kademe silme sadece MANUAL modda aktif — önce 3'e basın]",
        "min_levels":          "[En az 2 kademe gerekli — silme engellendi]",
        "level_updated":       "[Kademe güncellendi → {temp}°C : {rpm} RPM — daemon yeniden yüklendi]",
        "level_added":         "[Yeni kademe eklendi → {temp}°C : {rpm} RPM — daemon yeniden yüklendi]",
        "level_deleted":       "[Kademe silindi → {temp}°C : {rpm} RPM — daemon yeniden yüklendi]",
        "copied":              "[Durum panoya kopyalandı]",
        "log_error":           "[Log stream hatası: {e}]",
        # ── copy_status çıktısı ───────────────────────────────────────────
        "copy_mode_svc":       "Mod: {mode}  |  Servis: {status}",
        "copy_curve_title":    "FAN EĞRİSİ",
        # ── Silme onayı ───────────────────────────────────────────────────
        "del_confirm_msg":     "{temp}°C → {rpm} RPM kademesini sil?",
        # ── EditCurveModal ────────────────────────────────────────────────
        "modal_edit_title":    "Kademe {n} Düzenle",
        "modal_temp_label":    "Eşik sıcaklık (°C):",
        "modal_rpm_label":     "Fan hızı (RPM):",
        "save":                "Kaydet",
        # ── ConfirmModal ──────────────────────────────────────────────────
        "confirm_title":       "Onayla",
        "confirm_delete_btn":  "Sil",
    },
    "en": {
        # ── Binding labels ────────────────────────────────────────────────
        "quit":                "Quit",
        "refresh":             "Refresh",
        "copy":                "Copy",
        "mode_max":            "MAX mode",
        "mode_auto":           "AUTO mode",
        "mode_manual":         "MANUAL mode",
        "add":                 "Add",
        "delete":              "Delete",
        "cancel":              "Cancel",
        # ── Top bar buttons ───────────────────────────────────────────────
        "btn_max":             "1: MAX",
        "btn_auto":            "2: AUTO",
        "btn_manual":          "3: MANUAL",
        "svc_start":           "Start",
        "svc_stop":            "Stop",
        "svc_restart":         "Restart",
        # ── Panel titles ──────────────────────────────────────────────────
        "panel_temps":         "TEMPERATURES",
        "panel_fans":          "FANS",
        "panel_curve":         "FAN CURVE  (Enter/click to edit in MANUAL mode)",
        "panel_log":           "LOG  (journalctl -u hp-fan-curve)",
        # ── Table columns ─────────────────────────────────────────────────
        "col_threshold":       "Threshold (°C)",
        "col_rpm":             "Fan RPM",
        "col_status":          "Status",
        "active_marker":       "← ACTIVE",
        # ── Service label ─────────────────────────────────────────────────
        "service_label":       "Service",
        # ── Log messages ──────────────────────────────────────────────────
        "mode_changed":        "[Mode changed → {mode}]",
        "edit_only_manual":    "[Edit only available in MANUAL mode — press 3 first]",
        "add_only_manual":     "[Add level only available in MANUAL mode — press 3 first]",
        "del_only_manual":     "[Delete level only available in MANUAL mode — press 3 first]",
        "min_levels":          "[Minimum 2 levels required — delete blocked]",
        "level_updated":       "[Level updated → {temp}°C : {rpm} RPM — daemon reloaded]",
        "level_added":         "[New level added → {temp}°C : {rpm} RPM — daemon reloaded]",
        "level_deleted":       "[Level deleted → {temp}°C : {rpm} RPM — daemon reloaded]",
        "copied":              "[Status copied to clipboard]",
        "log_error":           "[Log stream error: {e}]",
        # ── copy_status output ────────────────────────────────────────────
        "copy_mode_svc":       "Mode: {mode}  |  Service: {status}",
        "copy_curve_title":    "FAN CURVE",
        # ── Delete confirm ────────────────────────────────────────────────
        "del_confirm_msg":     "Delete {temp}°C → {rpm} RPM level?",
        # ── EditCurveModal ────────────────────────────────────────────────
        "modal_edit_title":    "Edit Level {n}",
        "modal_temp_label":    "Threshold temp (°C):",
        "modal_rpm_label":     "Fan speed (RPM):",
        "save":                "Save",
        # ── ConfirmModal ──────────────────────────────────────────────────
        "confirm_title":       "Confirm",
        "confirm_delete_btn":  "Delete",
    },
}
