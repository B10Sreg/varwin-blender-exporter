import sys
import os
import subprocess
import bpy

def is_unitypy_available() -> bool:
    try:
        import UnityPy
        return True
    except ImportError:
        return False

def is_pillow_available() -> bool:
    try:
        import PIL
        return True
    except ImportError:
        return False

def get_dependency_status() -> dict:
    unitypy_ver = "не установлен"
    pillow_ver = "не установлен"
    try:
        import UnityPy
        unitypy_ver = getattr(UnityPy, '__version__', 'установлен')
    except Exception:
        pass

    try:
        import PIL
        pillow_ver = getattr(PIL, '__version__', 'установлен')
    except Exception:
        pass

    return {
        'unitypy': is_unitypy_available(),
        'unitypy_version': unitypy_ver,
        'pillow': is_pillow_available(),
        'pillow_version': pillow_ver,
    }

def install_package(package_name: str) -> tuple[bool, str]:
    """Installs a python package into Blender's bundled Python environment."""
    python_exe = sys.executable
    if not python_exe or not os.path.isfile(python_exe):
        return False, f"Исполняемый файл Python не найден: {python_exe}"

    # Ensure pip is available
    ensure_pip_cmd = [python_exe, "-m", "ensurepip", "--default-pip"]
    install_cmd = [python_exe, "-m", "pip", "install", "--upgrade", package_name]

    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        subprocess.run(ensure_pip_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo)
        res = subprocess.run(install_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo, timeout=180)
        if res.returncode == 0:
            return True, f"Пакет {package_name} успешно установлен!"
        else:
            err = res.stderr.strip() or res.stdout.strip()
            return False, f"Ошибка установки {package_name}: {err[:200]}"
    except Exception as e:
        return False, f"Исключение при вызове pip: {str(e)}"


class VARWIN_OT_install_dependencies(bpy.types.Operator):
    """Установить библиотеки UnityPy и Pillow во встроенный Python Blender"""
    bl_idname = "varwin.install_dependencies"
    bl_label = "Установить зависимости (UnityPy)"
    bl_description = "Автоматически устанавливает библиотеку UnityPy во встроенный Python Blender"
    bl_options = {'REGISTER', 'INTERNAL'}

    package: bpy.props.StringProperty(default="UnityPy")

    def execute(self, context):
        self.report({'INFO'}, f"Установка {self.package} через pip... Пожалуйста, подождите...")
        ok, msg = install_package(self.package)
        if ok:
            self.report({'INFO'}, f"Успех: {msg}")
            # Try to also install Pillow if needed
            if not is_pillow_available():
                install_package("Pillow")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, f"Не удалось установить: {msg}")
            return {'CANCELLED'}
