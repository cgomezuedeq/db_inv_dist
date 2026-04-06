## Backend (Python / FastAPI)

### Requisitos
- Python 3.10+

### Instalación
```bash
cd "c:\Users\CGOMEZU\Downloads\Dashboard inversiones\backend"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### Ejecutar
```bash
uvicorn app:app --reload --port 8001
```

### Variables de entorno (opcional)
- `EJE_XLSX`: ruta a `EJE.xlsx`
- `PPTO_XLSX`: ruta a `PPTO.xlsx`

