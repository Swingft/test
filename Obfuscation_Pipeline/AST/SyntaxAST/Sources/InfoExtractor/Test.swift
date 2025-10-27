//
//  TestMember.swift
//  SyntaxAST
//
//  Created by 백승혜 on 10/27/25.
//

import SwiftSyntax

struct EnumInfoExtractorTest {
    static func extract(from node: EnumDeclSyntax, locationHandler locationHandler: LocationHandler) -> [IdentifierInfo] {
        
        var memberList: [IdentifierInfo] = []
        for member in node.memberBlock.members {
            let decl = member.decl
            
            if let caseDecl = decl.as(EnumCaseDeclSyntax.self) {
                let accessLevels = ["private", "fileprivate", "internal", "public", "open"]
                let accessLevel = caseDecl.modifiers.compactMap {
                    modifier -> String? in
                    let name = modifier.name.text
                    return accessLevels.contains(name) ? name : nil
                }.first ?? "internal"
                
                let modifiers = caseDecl.modifiers ?? []
                let otherMods = modifiers.compactMap { modifier -> String? in
                    let name = modifier.name.text
                    return accessLevels.contains(name) ? nil : name
                }
                
                var attributes = (caseDecl.attributes ?? []).compactMap {
                    $0.as(AttributeSyntax.self)?.attributeName.description.trimmingCharacters(in: .whitespacesAndNewlines)
                }
                attributes.append(contentsOf: otherMods)
                var parameters: [String] = []
                var parameterType: [String] = []
                for element in caseDecl.elements {
                    let name = element.name.text
                    if let parameterClause = element.parameterClause {
                        for param in parameterClause.parameters {
                            let paramName = param.firstName?.text ?? "_"
                            let paramType = param.type.description.trimmingCharacters(in: .whitespacesAndNewlines)
                            parameters.append(paramName)
                            parameterType.append(paramType)
                        }
                    }
                    let info = IdentifierInfo(
                        A_name: name,
                        B_kind: "case",
                        C_accessLevel: accessLevel,
                        D_attributes: attributes,
                        F_location: locationHandler.findLocation(of: element),
                        I_parameters: parameters,
                        I_parameterType: parameterType
                    )
                    memberList.append(info)
                }
            } else if let varDecl = decl.as(VariableDeclSyntax.self) {
                let info = VariableInfoExtractor.extract(from: varDecl, locationHandler: locationHandler)
                memberList.append(contentsOf: info)
            } else if let funcDecl = decl.as(FunctionDeclSyntax.self) {
                let info = FunctionInfoExtractor.extract(from: funcDecl, locationHandler: locationHandler)
                memberList.append(info)
            } else if let enumDecl = decl.as(EnumDeclSyntax.self) {
                let info = EnumInfoExtractor.extract(from: enumDecl, locationHandler: locationHandler)
                memberList.append(info)
            } else if let structDecl = member.decl.as(StructDeclSyntax.self) {
                memberList.append(StructInfoExtractor.extract(from: structDecl, locationHandler: locationHandler))
            } else if let classDecl = member.decl.as(ClassDeclSyntax.self) {
                memberList.append(ClassInfoExtractor.extract(from: classDecl, locationHandler: locationHandler))
            } else if let initDecl = member.decl.as(InitializerDeclSyntax.self) {
                memberList.append(InitInfoExtractor.extract(from: initDecl, locationHandler: locationHandler))
            }
        }
        
        return memberList
    }
}
