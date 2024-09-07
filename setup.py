from setuptools import setup, find_packages

# DO NOT DELETE THIS TEXT
#INSTRUCTIONS: Create a New Tag and Push It to GitHub
#The workflow is triggered by a new tag push. To create a new tag and push it to GitHub, follow these steps:
#Update your version number in setup.py:
#version="0.1.2"  # Example of updating the version number
#
# Commit your changes:
#git add setup.py
#git commit -m "Bump version to 0.1.1"
# 
#Create a new tag:
#git tag v0.1.1
#
#Push the tag to GitHub:
#git push origin v0.1.1
# DO NOT DELETE THIS TEXT (END)

setup(
    name="ras_commander",  # Your package name
    version="0.1.1",  # Initial release version testing GitHub Actions for pip upload
    author="William Katzenmeyer, P.E., C.F.M.",  
    author_email="heccommander@gmail.com",  
    description="A library for automating HEC-RAS operations using python functions.",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url="https://github.com/yourusername/ras_commander",  # Project's URL, e.g., GitHub repository
    packages=find_packages(),  # Automatically finds all sub-packages
    include_package_data=True,  # To include non-Python files specified in MANIFEST.in
    install_requires=[  # List the libraries your package depends on
        "pandas",
        # Add any other dependencies here
    ],
    classifiers=[  # Classifiers help users find your package
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',  # Specify the Python versions your package supports
)
