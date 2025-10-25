//
//  ClassInfoExtractor.swift
//  SyntaxAST
//
//  Created by 백승혜 on 7/16/25.
//

import SwiftSyntax

struct ClassInfoExtractor {
    static func extract(from node: ClassDeclSyntax, locationHandler locationHandler: LocationHandler) -> IdentifierInfo {
        let name = node.name.text
        let kind = "class"
        
        let accessLevels = ["private", "fileprivate", "internal", "public", "open"]
        let accessLevel = node.modifiers.compactMap { modifier -> String? in
            let name = modifier.name.text
            return name
        }.first ?? "internal"
        
        let modifiers = node.modifiers ?? []
        let otherMods = modifiers.compactMap { modifier -> String? in
            let name = modifier.name.text
            return accessLevels.contains(name) ? nil : name
        }
        var attributes = (node.attributes ?? []).compactMap {
            $0.as(AttributeSyntax.self)?.attributeName.description.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        attributes.append(contentsOf: otherMods)
        
        let adoptedClassProtocols: [String]
        if let inheritanceClause = node.inheritanceClause {
            adoptedClassProtocols = inheritanceClause.inheritedTypeCollection.compactMap {
                $0.typeName.description.trimmingCharacters(in: .whitespacesAndNewlines)
            }
        } else {
            adoptedClassProtocols = []
        }
        
        let location = locationHandler.findLocation(of: node)
        
        var memberList: [IdentifierInfo] = []
        for member in node.memberBlock.members {
            if let funcDecl = member.decl.as(FunctionDeclSyntax.self) {
                memberList.append(FunctionInfoExtractor.extract(from: funcDecl, locationHandler: locationHandler))
            } else if let varDecl = member.decl.as(VariableDeclSyntax.self) {
                memberList.append(contentsOf: VariableInfoExtractor.extract(from: varDecl, locationHandler: locationHandler))
            } else if let enumDecl = member.decl.as(EnumDeclSyntax.self) {
                memberList.append(EnumInfoExtractor.extract(from: enumDecl, locationHandler: locationHandler))
            } else if let structDecl = member.decl.as(StructDeclSyntax.self) {
                memberList.append(StructInfoExtractor.extract(from: structDecl, locationHandler: locationHandler))
            } else if let classDecl = member.decl.as(ClassDeclSyntax.self) {
                memberList.append(ClassInfoExtractor.extract(from: classDecl, locationHandler: locationHandler))
            } else if let initDecl = member.decl.as(InitializerDeclSyntax.self) {
                memberList.append(InitInfoExtractor.extract(from: initDecl, locationHandler: locationHandler))
            }
        }
        
        return IdentifierInfo(
            A_name: name,
            B_kind: kind,
            C_accessLevel: accessLevel,
            D_attributes: attributes,
            E_adoptedClassProtocols: adoptedClassProtocols,
            F_location: location,
            G_members: memberList
        )
    }
}
