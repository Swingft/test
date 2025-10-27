// The Swift Programming Language
// https://docs.swift.org/swift-book

import Foundation
import SwiftParser

let mappingResultPath = CommandLine.arguments[1]
let sourceListPath = CommandLine.arguments[2]

let result = try readMappingResult(from: URL(filePath: mappingResultPath))
let mappingDict = result.reduce(into: [String: String]()) { dict, item in
    dict[item.target] = item.replacement
}

let fileList = try String(contentsOfFile: sourceListPath)
let sourcePaths = fileList.split(separator: "\n").map { String($0) }

for path in sourcePaths {
    let url = URL(fileURLWithPath: path)
    
    let fd = open(url.path, O_RDWR)
    if fd == -1 {
        fatalError()
    }
    if flock(fd, LOCK_EX) != 0 {
        fatalError()
    }
    
    let fileData = try Data(NSData(contentsOfFile: url.path, options: [.mappedIfSafe]))
    let sourceText = String(decoding: fileData, as: UTF8.self)
    let syntaxTree = try Parser.parse(source: sourceText)
    
    let rewriter = IDRewriter(mapping: mappingDict)
    let newSyntaxTree = rewriter.visit(syntaxTree)
    
    let newData = newSyntaxTree.description.data(using: .utf8)!
    
    lseek(fd, 0, SEEK_SET)
    ftruncate(fd, 0)
    
    try newData.withUnsafeBytes { ptr in
        let written = write(fd, ptr.baseAddress!, ptr.count)
        if written != ptr.count {
            fatalError()
        }
    }
    
    flock(fd, LOCK_UN)
    close(fd)
}
