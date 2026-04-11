"""
Tabela de margens de referencia por segmento/produto.
Baseada na tabela Pedro Della Nora - Formula do Lucro.

Cada entrada: (palavras_chave, margem_minima%, margem_maxima%, segmento)
A busca e feita por palavras-chave na descricao do produto do VR Master.
"""

TABELA_MARGENS = [
    # === ACOUGUE ===
    (["ave inteira", "frango inteiro", "galinha inteira"], 26, 26, "ACOUGUE"),
    (["salsicha granel", "calabresa granel"], 45, 45, "ACOUGUE"),
    (["frango temperado"], 38, 38, "ACOUGUE"),
    (["coxa", "sobrecoxa", "coxa e sobrecoxa"], 23, 23, "ACOUGUE"),
    (["suina temperada", "porco temperad"], 31, 31, "ACOUGUE"),
    (["carne suina", "porco"], 36, 36, "ACOUGUE"),
    (["bovina 1", "carne 1a", "primeira"], 34, 34, "ACOUGUE"),
    (["bovina 2", "carne 2a", "segunda"], 31, 31, "ACOUGUE"),
    (["bovina embalada"], 31, 31, "ACOUGUE"),
    (["linguicinha in natura", "linguica in natura"], 26, 26, "ACOUGUE"),
    (["miudo", "figado", "rim", "bucho"], 39, 39, "ACOUGUE"),
    (["bandeja", "carne bandeja"], 38, 38, "ACOUGUE"),
    (["charque", "carne de sol", "carne seca"], 30, 30, "ACOUGUE"),
    (["frango descongelado", "corte frango desc"], 30, 30, "ACOUGUE"),
    (["coxinha da asa", "asa marinad", "frango marinad", "asa de frango"], 30, 30, "ACOUGUE"),
    (["picanha"], 34, 34, "ACOUGUE"),
    (["alcatra", "maminha", "contra file", "file mignon", "patinho", "acem", "fraldinha", "costela", "paleta"], 31, 34, "ACOUGUE"),
    (["linguica churrasco", "linguica toscana", "linguica"], 26, 26, "ACOUGUE"),

    # === CONGELADOS ===
    (["hamburguer congelad", "hamburger congelad", "hamburguer bovino", "hamburguer frango"], 39, 39, "CONGELADOS"),
    (["batata frita", "batata congel"], 26, 26, "CONGELADOS"),
    (["lasanha", "lazanha"], 31, 31, "CONGELADOS"),
    (["pizza congelad"], 31, 31, "CONGELADOS"),
    (["frango iqf"], 35, 35, "CONGELADOS"),
    (["linguicinha congelad", "linguica congelad"], 31, 31, "CONGELADOS"),
    (["polpa fruta"], 43, 43, "CONGELADOS"),
    (["acai"], 27, 27, "CONGELADOS"),
    (["empanado"], 34, 34, "CONGELADOS"),
    (["pao de queijo", "pao queijo"], 30, 30, "CONGELADOS"),
    (["aves empanada"], 34, 34, "CONGELADOS"),
    (["nugget", "nuget"], 41, 41, "CONGELADOS"),
    (["peru natal"], 25, 25, "CONGELADOS"),
    (["peixe file", "peixe posta", "file peixe"], 31, 31, "CONGELADOS"),
    (["peixe inteiro"], 30, 35, "CONGELADOS"),
    (["salmao", "salmão"], 29, 29, "CONGELADOS"),
    (["camarao"], 30, 33, "CONGELADOS"),
    (["coracao", "moela", "pe dorso", "peito frango"], 32, 35, "CONGELADOS"),
    (["bacalhau"], 25, 25, "CONGELADOS"),
    (["carne ovelha"], 30, 30, "CONGELADOS"),
    (["carne porco cong", "porco congelad"], 35, 35, "CONGELADOS"),

    # === LEITE UHT ===
    (["leite uht", "leite integral", "leite semi", "leite desnatado"], 19, 19, "LEITE UHT"),
    (["leite zero lactose", "leite especial", "leite a2", "leite fiore", "leite sem lactose"], 22, 22, "LEITE UHT"),
    (["leite pacote", "leite saquinho"], 18, 20, "LEITE UHT"),

    # === FRIOS E LATICINIOS ===
    (["iogurte"], 32, 35, "FRIOS E LATICINIOS"),
    (["mussarela encartelad", "mussarela fatiada pct"], 31, 31, "FRIOS E LATICINIOS"),
    (["presunto", "apresuntado"], 32, 32, "FRIOS E LATICINIOS"),
    (["mortadela fatiada", "mortadela pct"], 32, 35, "FRIOS E LATICINIOS"),
    (["queijo especial", "queijo brie", "queijo gorgonzola"], 32, 32, "FRIOS E LATICINIOS"),
    (["pate"], 35, 35, "FRIOS E LATICINIOS"),
    (["massa fresca"], 35, 35, "FRIOS E LATICINIOS"),
    (["margarina"], 26, 26, "FRIOS E LATICINIOS"),
    (["requeijao"], 34, 34, "FRIOS E LATICINIOS"),
    (["nata"], 29, 31, "FRIOS E LATICINIOS"),
    (["manteiga"], 29, 31, "FRIOS E LATICINIOS"),
    (["queijo minas"], 33, 33, "FRIOS E LATICINIOS"),
    (["queijo prato"], 31, 31, "FRIOS E LATICINIOS"),
    (["mussarela fatiada local", "mussarela fatia"], 45, 45, "FRIOS E LATICINIOS"),
    (["presunto fatiado local", "presunto fatia"], 45, 45, "FRIOS E LATICINIOS"),
    (["salame fatiado"], 35, 35, "FRIOS E LATICINIOS"),
    (["salsicha pct", "salsicha pacote"], 35, 35, "FRIOS E LATICINIOS"),
    (["cream cheese", "creem cheese"], 35, 35, "FRIOS E LATICINIOS"),
    (["ricota"], 33, 33, "FRIOS E LATICINIOS"),
    (["pao de alho"], 28, 30, "FRIOS E LATICINIOS"),
    (["gelo"], 30, 33, "FRIOS E LATICINIOS"),
    (["mussarela peca", "mussarela inteira", "mussarela kg"], 28, 32, "FRIOS E LATICINIOS"),
    (["massa pastel"], 36, 36, "FRIOS E LATICINIOS"),

    # === EMBUTIDOS ===
    (["linguica defumada", "salame defumad"], 35, 35, "EMBUTIDOS"),
    (["mortadela inteira", "mortadela kg"], 30, 33, "EMBUTIDOS"),
    (["salame italiano"], 36, 36, "EMBUTIDOS"),
    (["bacon"], 34, 34, "EMBUTIDOS"),
    (["calabresa"], 31, 31, "EMBUTIDOS"),
    (["costelinha defumada"], 31, 31, "EMBUTIDOS"),
    (["banha"], 30, 33, "EMBUTIDOS"),
    (["torresmo"], 34, 34, "EMBUTIDOS"),

    # === PRODUTOS PARA CHURRASCO ===
    (["grelha"], 34, 34, "CHURRASCO"),
    (["espeto"], 34, 34, "CHURRASCO"),
    (["churrasqueira"], 34, 34, "CHURRASCO"),
    (["carvao"], 20, 22, "CHURRASCO"),
    (["acendedor carvao"], 48, 48, "CHURRASCO"),
    (["molho churrasco", "molho artesanal"], 33, 33, "CHURRASCO"),

    # === DIET / ZERO LACTOSE / ZERO GLUTEN ===
    (["zero acucar", "diet", "light"], 31, 31, "DIET/ZERO"),
    (["adocante"], 40, 40, "DIET/ZERO"),
    (["biscoito sem gluten", "biscoito s/ gluten"], 36, 36, "DIET/ZERO"),
    (["granola"], 31, 31, "DIET/ZERO"),
    (["geleia diet", "doce diet"], 34, 34, "DIET/ZERO"),
    (["acucar diet"], 34, 34, "DIET/ZERO"),
    (["macarrao integral", "macarrao s/ gluten"], 30, 30, "DIET/ZERO"),
    (["farinha de arroz"], 38, 38, "DIET/ZERO"),

    # === BISCOITOS ===
    (["biscoito amanteigado"], 28, 31, "BISCOITOS"),
    (["biscoito salgado", "cream cracker"], 28, 31, "BISCOITOS"),
    (["biscoito doce"], 28, 31, "BISCOITOS"),
    (["biscoito recheado"], 25, 29, "BISCOITOS"),
    (["biscoito rosca"], 25, 29, "BISCOITOS"),
    (["salgadinho", "doritos", "cheetos", "ruffles"], 31, 31, "BISCOITOS"),
    (["biscoito cookie"], 25, 29, "BISCOITOS"),
    (["wafer", "waffer"], 25, 29, "BISCOITOS"),
    (["amendoim japones", "amendoim coberto", "amendoim sem pele"], 30, 35, "BISCOITOS"),

    # === PADARIA FABRICACAO PROPRIA ===
    (["pao frances"], 70, 75, "PADARIA PROPRIA"),
    (["pao integral fab"], 66, 66, "PADARIA PROPRIA"),
    (["pao branco fab"], 66, 66, "PADARIA PROPRIA"),
    (["pao doce fab"], 66, 66, "PADARIA PROPRIA"),
    (["torta salgada fab"], 66, 66, "PADARIA PROPRIA"),
    (["bolo fab"], 66, 66, "PADARIA PROPRIA"),
    (["salgado frito fab"], 66, 66, "PADARIA PROPRIA"),
    (["salgado assado fab"], 66, 66, "PADARIA PROPRIA"),

    # === MASSAS ===
    (["macarrao com ovo", "macarrao ovos"], 31, 31, "MASSAS"),
    (["macarrao semola"], 31, 31, "MASSAS"),
    (["macarrao instantaneo", "miojo", "nissin"], 33, 33, "MASSAS"),
    (["macarrao grano duro"], 35, 35, "MASSAS"),
    (["massa lasanha", "massa lazanha"], 36, 36, "MASSAS"),
    (["queijo ralado"], 43, 43, "MASSAS"),
    (["sopao", "sopa maggi", "sopa knorr"], 45, 45, "MASSAS"),
    (["cup noodles", "cup noodle"], 35, 35, "MASSAS"),
    (["macarrao importado"], 29, 29, "MASSAS"),

    # === CONSERVAS E TEMPEROS ===
    (["maionese"], 25, 25, "CONSERVAS"),
    (["catchup", "ketchup", "mostarda"], 33, 33, "CONSERVAS"),
    (["extrato tomate"], 27, 27, "CONSERVAS"),
    (["molho tomate"], 35, 35, "CONSERVAS"),
    (["molho salada"], 35, 35, "CONSERVAS"),
    (["molho pimenta", "shoyu", "molho alho"], 35, 35, "CONSERVAS"),
    (["vinagre"], 33, 33, "CONSERVAS"),
    (["sardinha", "atum lata", "atum enlatad"], 35, 35, "CONSERVAS"),
    (["caldo", "caldo knorr", "caldo maggi"], 35, 35, "CONSERVAS"),
    (["condimento", "tempero", "oregano", "louro", "cominho"], 50, 50, "CONSERVAS"),
    (["azeitona"], 35, 35, "CONSERVAS"),
    (["pepino conserva"], 30, 30, "CONSERVAS"),
    (["ovo codorna"], 30, 30, "CONSERVAS"),
    (["milho lata", "ervilha", "duetto"], 30, 30, "CONSERVAS"),
    (["champignon", "alcaparra", "azeite dende"], 35, 35, "CONSERVAS"),
    (["feijoada lata", "salsicha lata"], 35, 35, "CONSERVAS"),
    (["palmito"], 30, 30, "CONSERVAS"),
    (["sazon"], 30, 30, "CONSERVAS"),

    # === BAZAR E UTILIDADES ===
    (["guardanapo"], 40, 40, "BAZAR"),
    (["copo descartavel", "prato descartavel"], 35, 35, "BAZAR"),
    (["garrafa termica"], 35, 35, "BAZAR"),
    (["vela"], 35, 35, "BAZAR"),
    (["fosforo"], 35, 35, "BAZAR"),
    (["filtro papel", "coador"], 35, 40, "BAZAR"),
    (["produto festa", "balao", "toalha mesa"], 50, 50, "BAZAR"),
    (["filme pvc", "saco freezer"], 35, 35, "BAZAR"),
    (["papel aluminio"], 35, 35, "BAZAR"),
    (["toalha papel"], 35, 35, "BAZAR"),
    (["lampada"], 35, 35, "BAZAR"),
    (["palito dental", "espetinho madeira"], 50, 50, "BAZAR"),
    (["chinelo", "havaianas"], 35, 35, "BAZAR"),
    (["caixa termica"], 35, 35, "BAZAR"),
    (["cadeira"], 35, 35, "BAZAR"),
    (["hidraulic", "eletric"], 43, 43, "BAZAR"),
    (["automotivo"], 35, 35, "BAZAR"),
    (["utilidade domestica"], 60, 60, "BAZAR"),
    (["chuveiro eletrico"], 35, 35, "BAZAR"),
    (["material escolar", "caderno", "lapis"], 35, 45, "BAZAR"),
    (["fumo", "cigarro papel"], 25, 30, "BAZAR"),
    (["gas cozinha", "gas glp", "botijao"], 15, 20, "BAZAR"),

    # === FRENTE DE CAIXA ===
    (["aparelho barbear", "gillete"], 43, 43, "FRENTE CAIXA"),
    (["pilha", "bateria"], 37, 37, "FRENTE CAIXA"),
    (["trident", "halls", "bala", "drops"], 37, 37, "FRENTE CAIXA"),
    (["chocolate barra pequen", "barra cereal"], 37, 37, "FRENTE CAIXA"),
    (["kinder ovo"], 34, 34, "FRENTE CAIXA"),
    (["brinquedo"], 37, 37, "FRENTE CAIXA"),
    (["super bonder"], 37, 37, "FRENTE CAIXA"),
    (["isqueiro"], 43, 43, "FRENTE CAIXA"),

    # === PADARIA INDUSTRIALIZADA ===
    (["pao congelado"], 35, 35, "PADARIA INDUST."),
    (["pao forma", "pao integral", "pao light", "pao tipo"], 26, 26, "PADARIA INDUST."),
    (["pao terceiriz", "pao outra padaria"], 28, 30, "PADARIA INDUST."),
    (["mini bolo"], 40, 40, "PADARIA INDUST."),
    (["panetone"], 25, 28, "PADARIA INDUST."),
    (["torrada"], 31, 31, "PADARIA INDUST."),
    (["bolo confeitado"], 30, 30, "PADARIA INDUST."),
    (["rap 10", "rap10", "tortilha"], 26, 28, "PADARIA INDUST."),
    (["pao de hamburguer", "pao hamburguer", "pao brioche", "hot dog", "pao hot dog", "industrializado pronto"], 34, 34, "PADARIA INDUST."),

    # === BEBIDAS ===
    (["refrigerante lata", "refrigerante lt"], 26, 30, "BEBIDAS"),
    (["refrigerante 600", "refrigerante pet 600", "refrigerante 200", "refrigerante pet 200", "refrigerante 250", "refrigerante pet 250", "refrigerante 300", "refrigerante pet 300"], 26, 30, "BEBIDAS"),
    (["refrigerante pet 1l", "refrigerante 1l"], 26, 30, "BEBIDAS"),
    (["refrigerante 1,5", "refrigerante 1.5", "coca cola 1,5", "coca 1.5", "refrigerante pet 1,5"], 18, 18, "BEBIDAS"),
    (["refrigerante 2l", "refrigerante pet 2", "coca cola 2", "coca 2", "refrigerante 2", "refrigerante 3l"], 18, 18, "BEBIDAS"),
    (["agua coco"], 30, 30, "BEBIDAS"),
    (["agua mineral"], 30, 33, "BEBIDAS"),
    (["aguardente", "cachaca", "aperitivo"], 30, 30, "BEBIDAS"),
    (["agua sabor", "agua saborizada"], 30, 33, "BEBIDAS"),
    (["suco concentrado", "suco 500", "suco 1l"], 30, 33, "BEBIDAS"),
    (["suco soja", "ades"], 30, 33, "BEBIDAS"),
    (["refresco po", "tang", "clight"], 27, 30, "BEBIDAS"),
    (["cha pronto"], 30, 30, "BEBIDAS"),
    (["conhaque", "whisky", "vodka", "gin"], 30, 33, "BEBIDAS"),
    (["licor", "batida"], 30, 33, "BEBIDAS"),
    (["xarope"], 30, 33, "BEBIDAS"),
    (["espumante", "sidra"], 35, 35, "BEBIDAS"),
    (["vinho"], 31, 31, "BEBIDAS"),
    (["isotonico", "gatorade", "powerade"], 30, 33, "BEBIDAS"),
    (["energetico", "red bull", "monster"], 30, 30, "BEBIDAS"),
    (["cerveja lata"], 18, 22, "BEBIDAS"),
    (["cerveja long neck"], 19, 22, "BEBIDAS"),
    (["cerveja garrafa", "cerveja 600"], 21, 21, "BEBIDAS"),
    (["chopp"], 20, 20, "BEBIDAS"),
    (["galao agua 20"], 20, 22, "BEBIDAS"),

    # === MATERIAL LIMPEZA ===
    (["sabao po"], 29, 29, "LIMPEZA"),
    (["lava roupa liquido", "lava roupas liq"], 31, 31, "LIMPEZA"),
    (["amaciante"], 30, 33, "LIMPEZA"),
    (["alvejante", "agua sanitaria", "cloro", "cloro puro"], 30, 33, "LIMPEZA"),
    (["coala"], 45, 45, "LIMPEZA"),
    (["sabao barra", "sabao liquido"], 27, 30, "LIMPEZA"),
    (["pedra sanitaria"], 38, 38, "LIMPEZA"),
    (["desinfetante"], 30, 33, "LIMPEZA"),
    (["inseticida"], 30, 33, "LIMPEZA"),
    (["saco lixo"], 30, 33, "LIMPEZA"),
    (["esponja"], 38, 40, "LIMPEZA"),
    (["la aco", "la de aco", "bombril"], 38, 40, "LIMPEZA"),
    (["limpa aluminio"], 35, 35, "LIMPEZA"),
    (["detergente"], 29, 29, "LIMPEZA"),
    (["sapolio", "sapólio"], 30, 33, "LIMPEZA"),
    (["limpa vidro"], 30, 33, "LIMPEZA"),
    (["limpa cozinha"], 31, 31, "LIMPEZA"),
    (["cera liquida", "cera pasta"], 28, 30, "LIMPEZA"),
    (["alcool gel", "alcool liquido", "alcool 70"], 31, 33, "LIMPEZA"),
    (["limpa forno"], 38, 38, "LIMPEZA"),
    (["multiuso", "multi uso"], 35, 40, "LIMPEZA"),
    (["limpeza pesada"], 36, 36, "LIMPEZA"),
    (["lustra movel", "lustra moveis"], 39, 39, "LIMPEZA"),
    (["odorizador", "bom ar"], 32, 32, "LIMPEZA"),
    (["anti mofo"], 40, 40, "LIMPEZA"),
    (["vassoura"], 35, 40, "LIMPEZA"),
    (["pano limpeza"], 35, 40, "LIMPEZA"),
    (["escova limpeza"], 38, 38, "LIMPEZA"),
    (["rodo"], 35, 40, "LIMPEZA"),
    (["limpador perfumado"], 36, 36, "LIMPEZA"),
    (["cloro gel"], 30, 35, "LIMPEZA"),
    (["desentupidor"], 50, 50, "LIMPEZA"),
    (["pa lixo"], 50, 50, "LIMPEZA"),
    (["luva limpeza", "luva latex"], 50, 50, "LIMPEZA"),
    (["soda caustica"], 22, 24, "LIMPEZA"),

    # === PET SHOP ===
    (["shampoo pet", "shampoo cao", "shampoo cachorro"], 50, 50, "PET SHOP"),
    (["racao ave", "racao passaro"], 36, 36, "PET SHOP"),
    (["racao gato"], 36, 36, "PET SHOP"),
    (["racao cao", "racao cachorro", "racao dog"], 36, 36, "PET SHOP"),
    (["acessorio pet", "coleira", "brinquedo pet"], 50, 50, "PET SHOP"),
    (["higiene pet", "limpeza pet"], 40, 40, "PET SHOP"),

    # === EMPORIO NATURAIS ===
    (["produto natural", "granola natural", "castanha", "chia", "linhaça", "quinoa"], 42, 55, "EMPORIO NATURAIS"),

    # === BOMBONIERE ===
    (["bombom caixa"], 26, 28, "BOMBONIERE"),
    (["bombom pct", "bombom 1kg"], 26, 28, "BOMBONIERE"),
    (["chocolate barra", "chocolate tableta"], 33, 37, "BOMBONIERE"),
    (["doce geral", "bala pct", "pirulito pct"], 33, 33, "BOMBONIERE"),
    (["fini"], 33, 33, "BOMBONIERE"),
    (["batata palha"], 31, 31, "BOMBONIERE"),
    (["ovo pascoa"], 20, 25, "BOMBONIERE"),

    # === MATINAIS ===
    (["cafe 250", "cafe 250g"], 34, 34, "MATINAIS"),
    (["cafe 500", "cafe 500g"], 26, 30, "MATINAIS"),
    (["cafe especial", "cafe gourmet"], 34, 34, "MATINAIS"),
    (["achocolatado po", "nescau", "toddy po"], 29, 29, "MATINAIS"),
    (["achocolatado liquido", "toddynho"], 35, 40, "MATINAIS"),
    (["cereal matinal", "sucrilhos", "corn flakes"], 35, 38, "MATINAIS"),
    (["amido milho", "maizena"], 34, 34, "MATINAIS"),
    (["aveia"], 34, 34, "MATINAIS"),
    (["coco ralado"], 43, 43, "MATINAIS"),
    (["doce fruta", "goiabada cascao"], 26, 30, "MATINAIS"),
    (["doce leite"], 26, 30, "MATINAIS"),
    (["fruta conserva", "pessego calda"], 35, 35, "MATINAIS"),
    (["gelatina"], 42, 42, "MATINAIS"),
    (["fermento quimico", "fermento po"], 26, 30, "MATINAIS"),
    (["fermento biologico"], 28, 28, "MATINAIS"),
    (["geleia", "mel", "melado"], 30, 35, "MATINAIS"),
    (["leite coco"], 35, 35, "MATINAIS"),
    (["leite po", "leite em po"], 29, 29, "MATINAIS"),
    (["cafe soluvel", "nescafe"], 31, 34, "MATINAIS"),
    (["cha sache", "cha caixa"], 35, 40, "MATINAIS"),
    (["erva chimarrao", "erva terere"], 26, 29, "MATINAIS"),
    (["mistura bolo"], 30, 30, "MATINAIS"),
    (["sobremesa"], 35, 42, "MATINAIS"),
    (["leite condensado"], 28, 32, "MATINAIS"),
    (["creme de leite"], 28, 32, "MATINAIS"),
    (["essencia", "chocolate granulado"], 43, 43, "MATINAIS"),
    (["chantilly"], 35, 35, "MATINAIS"),
    (["leite nan", "sustagem", "ensure"], 22, 25, "MATINAIS"),
    (["mucilon"], 34, 34, "MATINAIS"),
    (["coalho"], 30, 30, "MATINAIS"),
    (["goiabada"], 42, 42, "MATINAIS"),
    (["nutella", "nutela"], 32, 35, "MATINAIS"),

    # === CEREAIS ===
    (["acucar cristal 5", "acucar cristal 5kg"], 18, 20, "CEREAIS"),
    (["acucar cristal 2", "acucar cristal 2kg"], 27, 27, "CEREAIS"),
    (["acucar refinado 5", "acucar refinado 5kg"], 21, 21, "CEREAIS"),
    (["acucar refinado 1", "acucar refinado 1kg"], 30, 30, "CEREAIS"),
    (["acucar demerara", "acucar organico"], 30, 34, "CEREAIS"),
    (["farinha trigo 5", "farinha trigo 5kg"], 18, 20, "CEREAIS"),
    (["farinha trigo 1", "farinha trigo 1kg"], 30, 30, "CEREAIS"),
    (["arroz 5kg", "arroz 5 kg", "arroz tp1 5"], 20, 20, "CEREAIS"),
    (["arroz 1kg", "arroz 1 kg"], 29, 29, "CEREAIS"),
    (["arroz 2kg", "arroz 2 kg"], 29, 29, "CEREAIS"),
    (["fuba", "farinha milho"], 29, 29, "CEREAIS"),
    (["farinha mandioca", "farofa"], 30, 30, "CEREAIS"),
    (["feijao preto"], 22, 22, "CEREAIS"),
    (["feijao carioca"], 26, 26, "CEREAIS"),
    (["feijao caixinha"], 30, 30, "CEREAIS"),
    (["pipoca micro", "pipoca microondas"], 30, 30, "CEREAIS"),
    (["sal refinado", "sal iodado", "sal 1kg"], 43, 43, "CEREAIS"),
    (["sal temperado"], 43, 43, "CEREAIS"),
    (["oleo soja", "oleo de soja"], 17, 17, "CEREAIS"),
    (["oleo especial", "oleo canola", "oleo girassol"], 29, 29, "CEREAIS"),
    (["azeite oliva", "azeite"], 30, 33, "CEREAIS"),
    (["pipoca grao", "grao bico", "canjica", "lentilha"], 30, 30, "CEREAIS"),
    (["polvilho"], 31, 31, "CEREAIS"),
    (["massa tapioca", "tapioca"], 30, 33, "CEREAIS"),

    # === HORTIFRUTI ===
    (["fruta", "maca", "banana", "laranja", "mamao", "melancia", "uva", "morango"], 34, 34, "HORTIFRUTI"),
    (["legume", "tomate", "cebola", "batata", "cenoura", "pimentao"], 34, 34, "HORTIFRUTI"),
    (["raiz", "mandioca", "inhame", "beterraba"], 34, 34, "HORTIFRUTI"),
    (["ovo galinha", "ovos"], 26, 26, "HORTIFRUTI"),
    (["verdura", "alface", "couve", "rucula", "agriao"], 34, 34, "HORTIFRUTI"),
    (["alho pacote", "alho pct"], 34, 34, "HORTIFRUTI"),
    (["alho triturado"], 39, 39, "HORTIFRUTI"),

    # === HIGIENE PESSOAL E BELEZA ===
    (["absorvente"], 43, 43, "HIGIENE"),
    (["papel higienico", "papel hig"], 27, 31, "HIGIENE"),
    (["lenco umidecido", "lenco umedecido"], 36, 36, "HIGIENE"),
    (["haste flexivel", "cotonete", "algodao"], 43, 43, "HIGIENE"),
    (["produto infantil", "baby", "bebe"], 43, 43, "HIGIENE"),
    (["desodorante"], 38, 38, "HIGIENE"),
    (["sabonete", "creme dental", "pasta dente"], 40, 40, "HIGIENE"),
    (["esmalte", "manicure"], 46, 46, "HIGIENE"),
    (["escova dental", "fio dental"], 43, 43, "HIGIENE"),
    (["gel cabelo", "creme barba", "espuma barba"], 46, 46, "HIGIENE"),
    (["creme corpo", "oleo corpo", "hidratante"], 38, 38, "HIGIENE"),
    (["shampoo", "condicionador"], 36, 36, "HIGIENE"),
    (["creme cabelo", "creme pentear"], 40, 40, "HIGIENE"),
    (["repelente"], 36, 36, "HIGIENE"),
    (["antisseptico bucal", "enxaguante bucal", "listerine"], 45, 45, "HIGIENE"),
    (["protetor solar", "bronzeador"], 37, 37, "HIGIENE"),
    (["fralda"], 30, 30, "HIGIENE"),
    (["esponja banho"], 50, 50, "HIGIENE"),
    (["curativo", "acetona", "agua oxigenada"], 45, 45, "HIGIENE"),
    (["preservativo", "camisinha"], 37, 41, "HIGIENE"),
    (["tintura cabelo"], 35, 42, "HIGIENE"),
    (["lenco facial"], 43, 43, "HIGIENE"),
    (["escova cabelo"], 50, 50, "HIGIENE"),
    (["talco"], 42, 42, "HIGIENE"),
    (["sabonete intimo"], 30, 40, "HIGIENE"),
]


# === ITENS SENSIVEIS ===
# Produtos que devem SEMPRE estar com preco igual ou mais barato que a concorrencia.
# Nao subir preco desses itens mesmo que a margem esteja abaixo da tabela.
# Se o item estiver abaixo da margem, o alerta deve indicar que e item sensivel.
ITENS_SENSIVEIS = [
    "nissin",
    "lamem",
    "miojo",
    "coca cola 2",
    "coca 2l",
    "coca 2,5",
    "oleo de soja",
    "oleo soja",
    "maionese hellmann",
    "hellmanns",
    "extrato tomate elefante",
    "elefante 340",
    "biscoito passatempo",
    "passatempo",
    "leite ninho",
    "nescau",
    "toddy",
    "leite condensado",
    "creme de leite",
    "leite uht",
    "leite integral 1l",
    "leite semi 1l",
    "leite desnatado 1l",
    "sabonete dove",
    "dove sabonete",
    "desodorante dove",
    "dove desodorante",
    "sabao po omo",
    "omo 800",
    "omo 1,6",
    "omo 1.6",
    "sabao po tixan",
    "tixan 1kg",
    "tixan 2kg",
    "detergente ype",
    "detergente limpol",
    "ype 500",
    "limpol 500",
    "carne bovina",
    "cb ",
    "coxa",
    "sobrecoxa",
    "ovo galinha",
    "ovos",
    "cerveja lata",
    "cerveja lt",
    "tang",
    "refresco tang",
    "suco pronto 1l",
    "suco 1l",
    "ades 1l",
    "suco ades",
    "arroz 5kg",
    "arroz 5 kg",
    "arroz tp1 5",
    "feijao 1kg",
    "feijao 1 kg",
    "farinha trigo 5kg",
    "farinha trigo 5 kg",
]


def e_item_sensivel(descricao_produto):
    """
    Verifica se o produto e um item sensivel (deve manter preco competitivo).
    Retorna True se for sensivel.
    """
    desc_lower = descricao_produto.lower()
    desc_clean = desc_lower
    for old, new in [("ã", "a"), ("á", "a"), ("â", "a"), ("é", "e"), ("ê", "e"),
                     ("í", "i"), ("ó", "o"), ("ô", "o"), ("ú", "u"), ("ç", "c"),
                     ("ü", "u")]:
        desc_clean = desc_clean.replace(old, new)

    for kw in ITENS_SENSIVEIS:
        kw_clean = kw.lower()
        for old, new in [("ã", "a"), ("á", "a"), ("â", "a"), ("é", "e"), ("ê", "e"),
                         ("í", "i"), ("ó", "o"), ("ô", "o"), ("ú", "u"), ("ç", "c"),
                         ("ü", "u")]:
            kw_clean = kw_clean.replace(old, new)
        if kw_clean in desc_clean:
            return True
    return False


def encontrar_margem_esperada(descricao_produto):
    """
    Busca na tabela de margens a margem esperada para um produto
    baseado em palavras-chave na descricao.
    Retorna (margem_min, margem_max, segmento) ou None se nao encontrar.
    """
    desc_lower = descricao_produto.lower()
    # Remove acentos basicos para matching
    desc_clean = desc_lower
    for old, new in [("ã", "a"), ("á", "a"), ("â", "a"), ("é", "e"), ("ê", "e"),
                     ("í", "i"), ("ó", "o"), ("ô", "o"), ("ú", "u"), ("ç", "c"),
                     ("ü", "u")]:
        desc_clean = desc_clean.replace(old, new)

    melhor_match = None
    melhor_score = 0

    for keywords, margem_min, margem_max, segmento in TABELA_MARGENS:
        for keyword in keywords:
            kw_clean = keyword.lower()
            for old, new in [("ã", "a"), ("á", "a"), ("â", "a"), ("é", "e"), ("ê", "e"),
                             ("í", "i"), ("ó", "o"), ("ô", "o"), ("ú", "u"), ("ç", "c"),
                             ("ü", "u")]:
                kw_clean = kw_clean.replace(old, new)

            # Busca 1: substring direta (ex: "pao frances" em "pao frances kg")
            if kw_clean in desc_clean:
                score = len(kw_clean)
                if score > melhor_score:
                    melhor_score = score
                    melhor_match = (margem_min, margem_max, segmento)
            else:
                # Busca 2: todas as palavras da keyword existem no produto
                palavras_kw = kw_clean.split()
                if len(palavras_kw) > 1 and all(p in desc_clean for p in palavras_kw):
                    score = len(kw_clean)
                    if score > melhor_score:
                        melhor_score = score
                        melhor_match = (margem_min, margem_max, segmento)

    return melhor_match
