from distutils.core import setup

setup(
    name="pyunifiprotect",
    packages=["pyunifiprotect"],
    version="0.29.1",
    license="MIT",
    description="Python Wrapper for Unifi Protect API",
    author="Bjarne Riis",
    author_email="bjarne@briis.com",
    url="https://github.com/briis/pyunifiprotect",
    keywords=["UnifiProtect", "Surveilance", "Unifi", "Home Assistant", "Python"],
    install_requires=[
        "aiohttp",
        "asyncio",
        "pyjwt",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",  # Chose either "3 - Alpha", "4 - Beta" or "5 - Production/Stable" as the current state of your package
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
)
