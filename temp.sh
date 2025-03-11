apt install m4
tar -xzvf libdvd-audio.tar.gz; cd libdvd-audio
make clean
make
make install
ldconfig