# 📊 Dashboard Leads – Jimena

Dashboard en Streamlit que lee en tiempo real el Google Sheet de leads y muestra métricas de conversión.

## 🚀 Ejecución local

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Asegurarte de tener credentials.json en la raíz del proyecto
# (ya incluido — cuenta de servicio dashboardsaha)

# 3. Correr el dashboard
streamlit run app.py
```

Abre en el navegador: http://localhost:8501

---

## ☁️ Deploy en Streamlit Cloud

### Paso 1 – Subir el repositorio a GitHub

```bash
git init
git add app.py requirements.txt .streamlit/config.toml README.md
# NO añadir credentials.json ni .streamlit/secrets.toml
git commit -m "Dashboard Leads Jimena"
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

### Paso 2 – Crear app en share.streamlit.io

1. Ir a **share.streamlit.io** → *New app*
2. Conectar el repositorio GitHub
3. Main file: `app.py`

### Paso 3 – Configurar secretos

En *Settings → Secrets* del dashboard de Streamlit Cloud, pegar el contenido
de `.streamlit/secrets.toml.template` (renombrándolo mentalmente como `secrets.toml`).

**Formato:**
```toml
[gcp_service_account]
type = "service_account"
project_id = "dashboardsaha"
private_key_id = "..."
private_key = """-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----
"""
client_email = "dashboardsaha@dashboardsaha.iam.gserviceaccount.com"
...
```

### Paso 4 – Compartir el Google Sheet con la cuenta de servicio

Si aún no está compartido, en el Google Sheet:
1. Botón **Compartir**
2. Agregar: `dashboardsaha@dashboardsaha.iam.gserviceaccount.com`
3. Rol: **Lector**

---

## 📐 Lógica de negocio

### Pipeline de limpieza
| Paso | Descripción |
|------|-------------|
| 1 | Normalizar teléfono: quitar `+`, convertir notación científica a string |
| 2 | Filtrar nombres con "prueba", "undefined", "null", "." |
| 3 | Filtrar teléfonos que empiecen con "anon" o "anonymous" |
| 4 | Deduplicar por `telefono_norm`: mayor `campos_capturados` y fecha más reciente |

### Listo para cotizar
```
listo = resultado == "exitoso"
     OR (tiene placa AND ciudad AND fecha_nacimiento AND cédula)
```
> El correo es **opcional** para cotizar.

### Estados de lead
| Estado | Criterio |
|--------|----------|
| `exitoso` | `listo_cotizar == True` |
| `parcial` | 1–3 campos capturados |
| `abandono` | resultado == "abandono" |
| `sin_contestar` | Resto |

---

## 🔄 Auto-refresh

El dashboard se refresca automáticamente cada **5 minutos** usando `st.cache_data(ttl=300)` + `st.rerun()`.
El botón "Actualizar ahora" en el sidebar fuerza una recarga inmediata.
