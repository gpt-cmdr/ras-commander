from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
import subprocess
from pathlib import Path

class CustomBuildPy(build_py):
    def run(self):
        # Clean up __pycache__ folders
        root_dir = Path(__file__).parent
        for pycache_dir in root_dir.rglob('__pycache__'):
            if pycache_dir.is_dir():
                for cache_file in pycache_dir.iterdir():
                    cache_file.unlink()  # Delete each file
                pycache_dir.rmdir()      # Delete the empty directory
                print(f"Cleaned up: {pycache_dir}")

        # Run the summary_knowledge_bases.py script
        script_path = Path(__file__).parent / 'ai_tools' / 'generate_llm_knowledge_bases.py'
        try:
            subprocess.run(['python', str(script_path)], check=True)
        except subprocess.CalledProcessError:
            print("Warning: Knowledge base generation script failed, continuing with build")
        except FileNotFoundError:
            print("Warning: Knowledge base generation script not found, continuing with build")
        
        # Continue with the regular build process
        super().run()

setup(
    name="ras-commander",
    version="0.58.0",
    packages=find_packages(),
    include_package_data=True,
    python_requires='>=3.10',
    author="William M. Katzenmeyer, P.E., C.F.M.",
    author_email="heccommander@gmail.com",
    description="A Python library for automating HEC-RAS 6.x operations",
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    url="https://github.com/gpt-cmdr/ras-commander",
    cmdclass={
        'build_py': CustomBuildPy,
    },
    install_requires=[
        'h5py',
        'numpy',
        'pandas',
        'requests',
        'tqdm',
        'scipy',
        'xarray',
        'geopandas',
        'matplotlib',
        'shapely',
        'pathlib',
        'rasterstats',
        'rtree',
    ])

"""
ras-commander setup.py

This file is used to build and publish the ras-commander package to PyPI.

To build and publish this package, follow these steps:

1. Ensure you have the latest versions of setuptools, wheel, and twine installed:
   pip install --upgrade setuptools wheel twine

2. Update the version number in ras_commander/__init__.py (if not using automatic versioning)

3. Create source distribution and wheel:
   python setup.py sdist bdist_wheel

4. Check the distribution:
   twine check dist/*

5. Upload to Test PyPI (optional):
   twine upload --repository testpypi dist/*

6. Install from Test PyPI to verify (optional):
   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple ras-commander

7. Upload to PyPI:
   twine upload dist/* --username __token__ --password <your_api_key>


8. Install from PyPI to verify:
   pip install ras-commander

Note: Ensure you have the necessary credentials and access rights to upload to PyPI.
For more information, visit: https://packaging.python.org/tutorials/packaging-projects/

"""
