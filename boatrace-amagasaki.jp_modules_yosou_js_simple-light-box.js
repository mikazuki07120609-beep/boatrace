$(function(){
	var _body = $(window.parent.document.body);
	// var cssFile = false;

	$(".js-lightbox-btn").on("click", function(){
		var target 		= $(this).next(".js-lightbox-target").clone();
		var addClass	= $(this).attr("data-addClass") || '';
		var wHeight   	= $(window.parent.document).height();
		var wPosition 	= $(window.parent).scrollTop()+100;
		var createHtml 	= "";

		//同じスタイルシートを何度も読み込まないように
		// if(cssFile == false){
		// 	cssFile = "<link rel='stylesheet' href='/cdn/pc/css/yosou/simple-light-box.css?ver=1.1'>";
		// 	readCss = cssFile;
		// }

		createHtml =
			"<div class='js-lightbox "+addClass+"'>"
				+"<div class='background'></div>"
				+"<div class='bk-wrap'>"
					+"<a class='js-close-lightbox' href='javascript:void(0);'><i class='icon_close'></i></a>"
				+"</div>"
			+"</div>";

		_body.prepend(createHtml);
		$(".js-lightbox .bk-wrap", window.parent.document.body).append(target);
		$(".bk-wrap .js-lightbox-target", window.parent.document.body).css("display", "block");

		_body.find(".js-lightbox").css({
			"position": "absolute"
		});
		_body.find(".background").css({
			"width": "100%",
			"height": wHeight+"px",
			"position": "fixed"
		});
		_body.find(".bk-wrap").css({
			"top": wPosition+"px",
		});

	});

	///////////////////////////////////////////////////////////////
	/// ライトボックス削除処理
	///////////////////////////////////////////////////////////////
	_body.on("click", ".js-close-lightbox, .js-lightbox>.background", function(){
			_body.children(".js-lightbox").remove();
	})

});