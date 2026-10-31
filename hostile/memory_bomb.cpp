#include <cstring>
#include <vector>

int main() {
    std::vector<char*> blocks;
    while (true) {
        char* block = new char[10 * 1024 * 1024];
        std::memset(block, 1, 10 * 1024 * 1024);
        blocks.push_back(block);
    }
}
